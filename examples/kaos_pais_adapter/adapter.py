"""KAOS PAIS × SARC Governance adapter.

Copy this file into your KAOS deployment alongside a ``sarc_spec.yaml``
(mount it as a Kubernetes ConfigMap) and call ``build_governed_toolset``
wherever PAIS currently constructs ``DelegationToolset``.

Requirements:
    pip install sarc-governance          # this package
    # pais is part of kaos/pydantic-ai-server — install from source or your
    # internal registry; it is NOT required by sarc-governance itself.

Typical usage in pais/server.py (four lines):

    from sarc_governance.specs import load_spec
    from examples.kaos_pais_adapter.adapter import build_governed_toolset

    spec    = load_spec("/config/sarc_spec.yaml")
    toolset = build_governed_toolset(
        delegation_toolset=DelegationToolset(sub_agents, memory, session_id),
        agent_name=settings.agent_name,
        tenant_id=settings.tenant_id,
        spec=spec,
    )
    # use `toolset` wherever PAIS previously used `DelegationToolset`

Why no pais import here?
    ``GovernanceToolset`` wraps any object that satisfies ``ToolsetProtocol``
    — anything with ``async def call_tool(name, args, ctx, tool)``.
    ``DelegationToolset`` already has that signature, so no import or
    subclassing is needed.  This adapter is pure sarc-governance code.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sarc_governance import EscalationRouter, GovernanceToolset
from sarc_governance.constraints import ConstraintSpec
from sarc_governance.context import ExecutionContext
from sarc_governance.specs import load_spec as _load_spec
from sarc_governance.trace import TraceRecord

logger = logging.getLogger(__name__)


def build_governed_toolset(
    delegation_toolset: Any,
    agent_name: str,
    *,
    spec: Optional[ConstraintSpec] = None,
    spec_path: Optional[str] = None,
    tenant_id: str = "",
    roles: tuple = (),
    environment: str = "production",
    escalation_handler: Optional[Callable] = None,
) -> GovernanceToolset:
    """Wrap a KAOS ``DelegationToolset`` with SARC runtime governance.

    Parameters
    ----------
    delegation_toolset:
        A ``pais.tools.DelegationToolset`` instance (or any object whose
        ``call_tool`` signature matches ``ToolsetProtocol``).
    agent_name:
        The KAOS agent name (``$AGENT_NAME`` env var in PAIS).  Stamped onto
        every trace record for attribution.
    spec:
        A pre-loaded ``ConstraintSpec``.  Supply either ``spec`` or
        ``spec_path``, not both.
    spec_path:
        Filesystem path to a YAML spec file (e.g. a ConfigMap mount at
        ``/config/sarc_spec.yaml``).  Loaded once at startup.
    tenant_id:
        Tenant identifier for multi-tenant KAOS deployments.  Used by
        predicates that enforce cross-tenant isolation.
    roles:
        RBAC roles for the agent identity.  Available to predicates via
        ``ctx["execution_context"].roles``.
    environment:
        Deployment environment tag (``"production"``, ``"staging"``, …).
    escalation_handler:
        Async callable ``(record: TraceRecord, ctx: dict) -> None`` called
        when an escalation constraint fires.  Defaults to structured logging.
        Replace with your queue / ticketing / paging integration.

    Returns
    -------
    GovernanceToolset
        A drop-in replacement for ``delegation_toolset`` that enforces SARC
        constraints at PAG, ATM, and PAA around every tool call.
    """
    if spec is not None and spec_path is not None:
        raise ValueError("supply spec or spec_path, not both")
    if spec is None:
        if spec_path is None:
            raise ValueError("supply either spec or spec_path")
        spec = _load_spec(spec_path)

    router = EscalationRouter(handler=escalation_handler)

    # KAOS PAIS attaches an AgentDeps object at ctx.deps with .memory and
    # .session_id, which GovernanceToolset auto-detects for trace persistence.
    # The context_getter below builds a typed ExecutionContext from those deps
    # so that every trace record carries full agent identity.
    def context_getter(ctx: Any) -> Optional[ExecutionContext]:
        deps = getattr(ctx, "deps", None)
        if deps is None:
            return None
        session = getattr(deps, "session_id", "") or ""
        return ExecutionContext(
            agent_id=agent_name,
            tenant_id=tenant_id or getattr(deps, "tenant_id", ""),
            session_id=session,
            roles=roles or getattr(deps, "roles", ()),
            environment=environment,
        )

    return GovernanceToolset(
        wrapped=delegation_toolset,
        spec=spec,
        router=router,
        context_getter=context_getter,
        # memory_getter and session_id_getter are intentionally omitted:
        # GovernanceToolset auto-detects ctx.deps.memory / ctx.deps.session_id,
        # the exact shape PAIS produces via RunContext[AgentDeps].
    )
