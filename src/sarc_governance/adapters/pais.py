"""KAOS PAIS adapter helpers for sarc-governance.

This module provides three public objects for integrating SARC governance into
a KAOS PAIS deployment:

- :class:`PAISContextMapper` — maps ``ctx.deps`` (PAIS ``AgentDeps``) to a
  typed :class:`~sarc_governance.context.ExecutionContext`.  Use this to stamp
  tenant_id, roles, principal_id, and environment onto every trace record, since
  PAIS ``AgentDeps`` does not provide those fields by default.

- :class:`PAISMemoryGuard` — wraps any PAIS memory object and ensures the
  session exists (via ``create()``) before the first ``add_event()`` call for
  that session.  Without this guard, PAIS memory silently drops events for
  sessions that have not been explicitly created, causing silent trace losses.

- :func:`build_governed_toolset` — combines the above into a
  :class:`~sarc_governance.governance.GovernanceToolset` that wraps a PAIS
  ``DelegationToolset`` (or any object satisfying ``ToolsetProtocol``).

Scope of governance
-------------------
SARC governs **only the tool boundaries that are explicitly wrapped** by the
returned :class:`~sarc_governance.governance.GovernanceToolset`.  MCP tools or
PAIS sub-agents that are called outside the wrapper are not governed, even if
they are registered in the same PAIS agent registry.

No pais dependency
------------------
This module does not import ``pais`` or ``kaos`` at load time.
``GovernanceToolset`` wraps any object that satisfies ``ToolsetProtocol``
(``async def call_tool(name, args, ctx, tool)``), which ``DelegationToolset``
already satisfies.  Install and import ``pais`` in your own code; pass the
``DelegationToolset`` instance to :func:`build_governed_toolset`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from sarc_governance.constraints import ConstraintSpec
from sarc_governance.context import ExecutionContext
from sarc_governance.escalation import EscalationRouter
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
    wrapped object unchanged, and never raises on ``create()`` failures (the
    session may already exist).

    Usage::

        guard = PAISMemoryGuard(ctx.deps.memory)
        await guard.add_event(session_id, "governance_event", record.to_dict())
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
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
                    _log.debug(
                        "PAISMemoryGuard.create(%r) raised (session may already exist): %s",
                        session_id,
                        exc,
                    )
            self._known.add(session_id)
        return await self._inner.add_event(session_id, event_type, content, metadata)


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
    escalation_handler: Optional[Callable] = None,
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
    "PAISContextMapper",
    "PAISMemoryGuard",
    "build_governed_toolset",
]
