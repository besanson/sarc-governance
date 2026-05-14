"""KAOS PAIS adapter helpers for sarc-governance.

This module provides five public objects for integrating SARC governance into
a KAOS PAIS deployment:

- :class:`SARCGovernanceToolset` — a pydantic-ai ``AbstractToolset``-compatible
  wrapper that enforces SARC PAG/ATM/PAA constraints around any KAOS toolset
  (``DelegationToolset``, ``MCPServerStreamableHTTP``, or any compatible object).
  Designed for use with :func:`create_governed_agent_server`.

- :func:`create_governed_agent_server` — the canonical production entry point.
  Calls KAOS's ``create_agent_server(**kwargs)`` normally, then replaces every
  toolset in ``server._agent._toolsets`` with a :class:`SARCGovernanceToolset`
  wrapper.  Returns the fully-configured ``AgentServer``.  No KAOS source
  modification required.

- :class:`PAISContextMapper` — maps ``ctx.deps`` (PAIS ``AgentDeps``) to a
  typed :class:`~sarc_governance.context.ExecutionContext`.  Use this to stamp
  tenant_id, roles, principal_id, and environment onto every trace record, since
  PAIS ``AgentDeps`` does not provide those fields by default.

- :class:`PAISMemoryGuard` — wraps any PAIS memory object and ensures the
  session exists (via ``create()``) before the first ``add_event()`` call for
  that session.  Without this guard, PAIS memory silently drops events for
  sessions that have not been explicitly created, causing silent trace losses.

- :func:`build_governed_toolset` — wraps a single toolset (legacy pattern,
  kept for backwards compatibility).  For new deployments prefer
  :func:`create_governed_agent_server`.

Canonical production pattern
-----------------------------
Use :func:`create_governed_agent_server` as a drop-in replacement for KAOS's
``create_agent_server``::

    from sarc_governance.adapters.pais import create_governed_agent_server
    from sarc_governance import load_spec

    spec   = load_spec("/config/sarc_spec.yaml")
    server = create_governed_agent_server(
        spec,
        agent_name="my-agent",
        tenant_id="acme-corp",
    )
    # server.app is a fully-governed FastAPI app — use it like the KAOS default.

This wraps *all* toolsets that ``create_agent_server`` registers (both
``DelegationToolset`` sub-agent routing and MCP tool calls), without any
modification to the KAOS source.

Scope of governance
-------------------
SARC governs **only the tool boundaries that are explicitly wrapped** by the
returned :class:`SARCGovernanceToolset` (or :class:`~sarc_governance.governance.GovernanceToolset`).
Tools called directly by sub-agents outside that wrapper are not governed.

No pais dependency at import time
----------------------------------
This module does not import ``pais`` or ``pydantic-ai`` at load time.
Both are imported lazily inside :func:`create_governed_agent_server`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from sarc_governance.constraints import ConstraintSpec
from sarc_governance.context import ExecutionContext
from sarc_governance.escalation import EscalationHandler, EscalationRouter
from sarc_governance.governance import GovernanceToolset

_log = logging.getLogger(__name__)


class PAISContextMapper:
    """Map PAIS ``ctx.deps`` to a SARC :class:`~sarc_governance.context.ExecutionContext`.

    PAIS ``AgentDeps`` exposes ``session_id`` and ``memory`` but does not
    provide ``tenant_id``, ``roles``, ``principal_id``, or ``environment`` by
    default.  Supply those at construction time for multi-tenant or
    RBAC-governed deployments.  Per-call values on ``ctx.deps`` (e.g.
    ``deps.tenant_id``) are used as fallback when the constructor values are
    empty.

    Usage::

        mapper = PAISContextMapper(
            agent_name="procurement-approver",
            tenant_id="acme-corp",
            roles=("procurement-manager",),
            environment="production",
        )
        governed = GovernanceToolset(
            wrapped=delegation_toolset,
            spec=spec,
            context_getter=mapper,
        )
    """

    def __init__(
        self,
        agent_name: str,
        *,
        tenant_id: str = "",
        roles: Tuple[str, ...] = (),
        environment: str = "production",
        principal_id: str = "",
    ) -> None:
        self.agent_name = agent_name
        self.tenant_id = tenant_id
        self.roles = roles
        self.environment = environment
        self.principal_id = principal_id

    def __call__(self, ctx: Any) -> Optional[ExecutionContext]:
        deps = getattr(ctx, "deps", None)
        if deps is None:
            return None
        return ExecutionContext(
            agent_id=self.agent_name,
            principal_id=self.principal_id or getattr(deps, "principal_id", ""),
            tenant_id=self.tenant_id or getattr(deps, "tenant_id", ""),
            session_id=getattr(deps, "session_id", "") or "",
            roles=tuple(self.roles) if self.roles else tuple(getattr(deps, "roles", ())),
            environment=self.environment,
        )


class PAISMemoryGuard:
    """Wrap a PAIS memory object and ensure sessions exist before ``add_event``.

    PAIS memory (and the ``FakeMemory`` test double) silently drops
    ``add_event`` calls when the session has not been explicitly created via
    ``create(session_id)``.  This wrapper calls ``create()`` once per
    ``session_id`` before the first event is persisted, preventing silent
    governance trace drops.

    The guard is transparent: it delegates every ``add_event`` call to the
    wrapped object unchanged.

    Parameters
    ----------
    inner:
        The wrapped PAIS memory object.
    strict:
        When ``True``, any exception raised by ``inner.create()`` is
        re-raised immediately rather than being swallowed.  Use this to
        surface session initialisation failures early in deployments where
        ``create()`` should never fail (e.g. the session is pre-created by
        the caller).  Default is ``False`` (log at WARNING and continue).

    Usage::

        guard = PAISMemoryGuard(ctx.deps.memory)
        await guard.add_event(session_id, "governance_event", record.to_dict())

        # Fail fast if session creation fails:
        guard = PAISMemoryGuard(ctx.deps.memory, strict=True)
    """

    def __init__(self, inner: Any, *, strict: bool = False) -> None:
        self._inner = inner
        self._strict = strict
        self._known: set[str] = set()

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if session_id and session_id not in self._known:
            create = getattr(self._inner, "create", None)
            if callable(create):
                try:
                    result = create(session_id)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    if self._strict:
                        raise
                    _log.warning(
                        "PAISMemoryGuard: create(%r) raised — governance traces for this "
                        "session may be silently dropped by the underlying memory. "
                        "Pass strict=True to surface this as an error. Cause: %s",
                        session_id,
                        exc,
                    )
            self._known.add(session_id)
        return await self._inner.add_event(session_id, event_type, content, metadata)


class SARCGovernanceToolset:
    """Pydantic-AI AbstractToolset-compatible wrapper that enforces SARC constraints.

    Implements the pydantic-ai ``AbstractToolset`` duck-typed interface:
    ``id`` property, ``get_tools(ctx)``, ``call_tool(name, tool_args, ctx, tool)``.

    The KAOS agent runtime calls these methods identically to any other
    registered toolset — SARC constraints are enforced transparently.

    ``get_tools`` is delegated directly to the wrapped toolset (pydantic-ai uses
    this to build its tool schema for the LLM).  ``call_tool`` routes through
    :class:`~sarc_governance.governance.GovernanceToolset`, enforcing PAG/ATM/PAA
    before and after the inner toolset's ``call_tool``.

    Do not instantiate directly.  Use :func:`create_governed_agent_server`, which
    builds one instance per toolset registered in the KAOS ``AgentServer``.
    """

    def __init__(self, wrapped: Any, governance: GovernanceToolset) -> None:
        self._wrapped = wrapped
        self._governance = governance

    @property
    def id(self) -> str:
        return getattr(self._wrapped, "id", "sarc-governed")

    async def get_tools(self, ctx: Any) -> Any:
        return await self._wrapped.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        return await self._governance.call_tool(name, tool_args, ctx, tool)


def create_governed_agent_server(
    spec: Optional[ConstraintSpec] = None,
    *,
    spec_path: Optional[str] = None,
    agent_name: str = "",
    tenant_id: str = "",
    roles: Tuple[str, ...] = (),
    environment: str = "production",
    principal_id: str = "",
    guard_memory: bool = True,
    escalation_handler: Optional[EscalationHandler] = None,
    **kaos_kwargs: Any,
) -> Any:
    """Create a KAOS AgentServer with all toolsets governed by SARC constraints.

    This is the **canonical production entry point** for KAOS/PAIS deployments.
    It calls KAOS's ``create_agent_server(**kaos_kwargs)`` normally — no source
    modification to KAOS is required — then replaces every toolset in
    ``server._agent._toolsets`` with a :class:`SARCGovernanceToolset` wrapper.

    The returned ``AgentServer`` is fully governed: every tool call routed
    through any of its registered toolsets (sub-agent delegation via
    ``DelegationToolset`` and MCP tool calls via ``MCPServerStreamableHTTP``)
    passes through SARC's PAG/ATM/PAA enforcement loop.

    Parameters
    ----------
    spec:
        Pre-built :class:`~sarc_governance.constraints.ConstraintSpec`.
        Exactly one of ``spec`` or ``spec_path`` must be supplied.
    spec_path:
        Filesystem path to a YAML spec (e.g. a Kubernetes ConfigMap mount at
        ``/config/sarc_spec.yaml``).  Loaded once at startup.
    agent_name:
        KAOS agent identifier (e.g. from ``$AGENT_NAME``).  Stamped on every
        trace record as ``agent_id``.  Falls back to ``kaos_kwargs["settings"]
        .agent_name`` when left empty.
    tenant_id:
        Tenant identifier for multi-tenant deployments.  Falls back to
        ``ctx.deps.tenant_id`` at call time when empty.
    roles:
        RBAC roles for predicate evaluation.  Falls back to ``ctx.deps.roles``
        when empty.
    environment:
        Deployment environment tag (``"production"``, ``"staging"``, …).
    principal_id:
        Principal identifier.  Falls back to ``ctx.deps.principal_id`` when
        empty.
    guard_memory:
        When ``True`` (default), wraps ``ctx.deps.memory`` with
        :class:`PAISMemoryGuard` so that sessions are created automatically on
        first ``add_event`` (prevents silent trace drops for stub/test memory
        backends).  Set to ``False`` when using real ``pais.memory.LocalMemory``
        with pre-created sessions or when your backend auto-creates sessions.
    escalation_handler:
        Async callable ``(record: TraceRecord, ctx: dict) -> None`` invoked
        when an escalation constraint fires.  Defaults to structured logging.
    **kaos_kwargs:
        Keyword arguments forwarded verbatim to ``pais.server.create_agent_server``.
        See KAOS documentation for the full list (``settings``, ``sub_agents``,
        ``custom_agent``, …).

    Returns
    -------
    AgentServer
        The KAOS ``AgentServer`` instance, with every toolset wrapped by SARC
        governance.  Use ``server.app`` as your FastAPI application.

    Raises
    ------
    ImportError
        If ``pais`` (``pydantic-ai-server``) is not installed.
    ValueError
        If neither or both of ``spec`` and ``spec_path`` are supplied.

    Example
    -------
    ::

        from sarc_governance.adapters.pais import create_governed_agent_server
        from sarc_governance import load_spec

        spec   = load_spec("/config/sarc_spec.yaml")
        server = create_governed_agent_server(
            spec,
            agent_name=settings.agent_name,
            tenant_id=settings.tenant_id,
        )
        app = server.app  # FastAPI application — use as your WSGI/ASGI entrypoint
    """
    if (spec is None) == (spec_path is None):
        raise ValueError("supply exactly one of spec= or spec_path=")

    if spec_path is not None:
        from sarc_governance.specs import load_spec

        spec = load_spec(spec_path)

    try:
        from pais.server import create_agent_server
    except ImportError as exc:
        raise ImportError(
            "pais (pydantic-ai-server) is required for create_governed_agent_server. "
            "Install it: pip install pydantic-ai-server  "
            "or: pip install -e path/to/kaos/pydantic-ai-server"
        ) from exc

    # Resolve agent_name from KAOS settings if not explicitly supplied.
    resolved_agent_name = agent_name
    if not resolved_agent_name:
        settings = kaos_kwargs.get("settings")
        if settings is not None:
            resolved_agent_name = getattr(settings, "agent_name", "") or ""

    router = EscalationRouter(handler=escalation_handler)
    context_mapper = PAISContextMapper(
        resolved_agent_name,
        tenant_id=tenant_id,
        roles=roles,
        environment=environment,
        principal_id=principal_id,
    )

    memory_getter: Optional[Callable] = None
    session_id_getter: Optional[Callable] = None

    if guard_memory:
        _guard_cache: Dict[int, PAISMemoryGuard] = {}

        def _guarded_memory(ctx: Any) -> Optional[PAISMemoryGuard]:
            deps = getattr(ctx, "deps", None)
            if deps is None:
                return None
            inner = getattr(deps, "memory", None)
            if inner is None:
                return None
            key = id(inner)
            if key not in _guard_cache:
                _guard_cache[key] = PAISMemoryGuard(inner)
            return _guard_cache[key]

        def _session_id(ctx: Any) -> str:
            deps = getattr(ctx, "deps", None)
            if deps is None:
                return ""
            return getattr(deps, "session_id", "") or ""

        memory_getter = _guarded_memory
        session_id_getter = _session_id

    assert spec is not None  # guaranteed by the guard above; reassures type checker

    server = create_agent_server(**kaos_kwargs)

    governed_toolsets = []
    for ts in list(getattr(server._agent, "_toolsets", [])):
        governance = GovernanceToolset(
            wrapped=ts,
            spec=spec,
            router=router,
            context_getter=context_mapper,
            memory_getter=memory_getter,
            session_id_getter=session_id_getter,
        )
        governed_toolsets.append(SARCGovernanceToolset(wrapped=ts, governance=governance))

    server._agent._toolsets = governed_toolsets
    _log.info(
        "SARC governance applied to %d toolset(s) on agent %r",
        len(governed_toolsets),
        resolved_agent_name or "(unnamed)",
    )
    return server


def build_governed_toolset(
    delegation_toolset: Any,
    agent_name: str,
    *,
    spec: Optional[ConstraintSpec] = None,
    spec_path: Optional[str] = None,
    tenant_id: str = "",
    roles: Tuple[str, ...] = (),
    environment: str = "production",
    principal_id: str = "",
    guard_memory: bool = True,
    escalation_handler: Optional[EscalationHandler] = None,
) -> GovernanceToolset:
    """Wrap a KAOS PAIS ``DelegationToolset`` with SARC runtime governance.

    This is the canonical library function for PAIS integration.  The example
    at ``examples/kaos_pais_adapter/adapter.py`` delegates to this function.

    Scope of governance
    -------------------
    SARC governs **only tool calls routed through the returned**
    ``GovernanceToolset``.  MCP tools, sub-agents, or PAIS tools that bypass
    this wrapper are not governed.  Wire the returned toolset as the single
    entry point for all governed tool calls.

    Parameters
    ----------
    delegation_toolset:
        A ``pais.tools.DelegationToolset`` instance, or any object satisfying
        ``ToolsetProtocol`` (``async def call_tool(name, args, ctx, tool)``).
    agent_name:
        KAOS agent identifier (e.g. ``$AGENT_NAME``).  Stamped on every trace
        record as ``agent_id`` for attribution.
    spec:
        Pre-built :class:`~sarc_governance.constraints.ConstraintSpec`.
        Exactly one of ``spec`` or ``spec_path`` must be supplied.
    spec_path:
        Filesystem path to a YAML spec (e.g. a Kubernetes ConfigMap mount at
        ``/config/sarc_spec.yaml``).  Loaded once at startup.
    tenant_id:
        Tenant identifier for multi-tenant deployments.  When empty, falls back
        to ``ctx.deps.tenant_id`` at call time.
    roles:
        RBAC roles for predicate evaluation.  When empty, falls back to
        ``ctx.deps.roles`` at call time.
    environment:
        Deployment environment tag (``"production"``, ``"staging"``, …).
    principal_id:
        Principal (user/service) identifier.  When empty, falls back to
        ``ctx.deps.principal_id`` at call time.
    guard_memory:
        When ``True`` (default), wrap ``ctx.deps.memory`` with
        :class:`PAISMemoryGuard` to ensure sessions exist before ``add_event``
        is called.  Set to ``False`` only if your PAIS memory implementation
        creates sessions automatically.
    escalation_handler:
        Async callable ``(record: TraceRecord, ctx: dict) -> None`` invoked
        when an escalation constraint fires.  Defaults to structured logging.

    Returns
    -------
    GovernanceToolset
        Drop-in replacement for ``delegation_toolset``.  Use it wherever PAIS
        currently constructs ``DelegationToolset``.
    """
    if (spec is None) == (spec_path is None):
        raise ValueError("supply exactly one of spec= or spec_path=")

    if spec_path is not None:
        from sarc_governance.specs import load_spec

        spec = load_spec(spec_path)

    router = EscalationRouter(handler=escalation_handler)
    context_mapper = PAISContextMapper(
        agent_name,
        tenant_id=tenant_id,
        roles=roles,
        environment=environment,
        principal_id=principal_id,
    )

    memory_getter: Optional[Callable] = None
    session_id_getter: Optional[Callable] = None

    if guard_memory:
        _guard_cache: Dict[int, PAISMemoryGuard] = {}

        def _guarded_memory(ctx: Any) -> Optional[PAISMemoryGuard]:
            deps = getattr(ctx, "deps", None)
            if deps is None:
                return None
            inner = getattr(deps, "memory", None)
            if inner is None:
                return None
            key = id(inner)
            if key not in _guard_cache:
                _guard_cache[key] = PAISMemoryGuard(inner)
            return _guard_cache[key]

        def _session_id(ctx: Any) -> str:
            deps = getattr(ctx, "deps", None)
            if deps is None:
                return ""
            return getattr(deps, "session_id", "") or ""

        memory_getter = _guarded_memory
        session_id_getter = _session_id

    assert spec is not None  # guaranteed by the guard above; reassures type checker
    return GovernanceToolset(
        wrapped=delegation_toolset,
        spec=spec,
        router=router,
        context_getter=context_mapper,
        memory_getter=memory_getter,
        session_id_getter=session_id_getter,
    )


__all__ = [
    "SARCGovernanceToolset",
    "create_governed_agent_server",
    "PAISContextMapper",
    "PAISMemoryGuard",
    "build_governed_toolset",
]
