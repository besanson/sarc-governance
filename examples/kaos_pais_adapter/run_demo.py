#!/usr/bin/env python3
"""KAOS PAIS adapter for SARC.

KAOS (https://github.com/axsaucedo/kaos) is a Kubernetes-native platform that
runs Pydantic AI agents (via the Pydantic AI Server, PAIS) and wires them to
MCP tool servers and sub-agents.  Every tool call — both MCP calls and
agent-to-agent delegations — flows through ``DelegationToolset.call_tool``
in ``pais/tools.py``.  That signature already satisfies ``ToolsetProtocol``,
so ``GovernanceToolset`` wraps it without modification.

KAOS's ``Memory`` class (``pais/memory.py``) already has the exact signature
that ``MemoryProtocol`` requires::

    async def add_event(session_id, event_type, content, metadata) -> None

So governance trace records are persisted into the same PAIS session memory
that KAOS uses for conversation history — no second storage system needed.

Integration recipe (four lines in pais/tools.py):

    from sarc_governance import GovernanceToolset
    from sarc_governance.specs import load_spec

    spec    = load_spec("/config/sarc_spec.yaml")   # K8s ConfigMap mount
    toolset = GovernanceToolset(wrapped=DelegationToolset(...), spec=spec)
    # then use `toolset` wherever PAIS currently uses `DelegationToolset`

This file is a dependency-free demo.  The KAOS types are replaced by
stand-ins that mirror the public shapes in pais/tools.py, pais/memory.py,
and pais/serverutils.py well enough that the wiring is obvious.

Run::

    python examples/kaos_pais_adapter/run_demo.py
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    EscalationRouter,
    GovernanceToolset,
)
from sarc_governance.context import ExecutionContext
from sarc_governance.trace import TraceRecord


# ---------------------------------------------------------------------------
# KAOS PAIS stand-ins — mirror the public shapes; no kaos/pais dependency.
# ---------------------------------------------------------------------------


@dataclass
class MemoryEvent:
    event_id: str
    session_id: str
    event_type: str
    content: Any
    metadata: Optional[Dict[str, Any]] = None


class PAISMemory:
    """Stand-in for pais.memory.LocalMemory.

    The real class has the same ``add_event`` signature, so this drops in
    without change.  ``GovernanceToolset`` uses it via ``MemoryProtocol``.
    """

    def __init__(self) -> None:
        self._events: List[MemoryEvent] = []

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._events.append(
            MemoryEvent(
                event_id=str(uuid.uuid4()),
                session_id=session_id,
                event_type=event_type,
                content=content,
                metadata=metadata,
            )
        )

    def governance_events(self) -> List[MemoryEvent]:
        return [e for e in self._events if e.event_type == "governance_event"]


@dataclass
class AgentDeps:
    """Stand-in for the deps object PAIS attaches to the Pydantic AI context.

    ``GovernanceToolset`` auto-detects ``ctx.deps.memory`` and
    ``ctx.deps.session_id`` when no explicit getters are supplied, so this
    shape requires zero extra wiring.
    """

    memory: PAISMemory
    session_id: str
    agent_name: str
    tenant_id: str = ""
    roles: tuple = ()


@dataclass
class PAISContext:
    """Stand-in for pydantic_ai.RunContext[AgentDeps] that PAIS produces."""

    deps: AgentDeps


class MockSubAgent:
    """Stand-in for pais.serverutils.RemoteAgent.

    In production this calls ``POST /v1/chat/completions`` on the target agent
    pod via HTTP.  Here it just echoes the task back so the demo has no
    network dependency.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: List[Dict[str, Any]] = []

    async def process_message(self, task: str, context: Dict[str, Any]) -> str:
        self.calls.append({"task": task, "context": context})
        return f"{self.name} completed: {task}"


class KAOSDelegationToolset:
    """Stand-in for pais.tools.DelegationToolset.

    The real class exposes registered sub-agents as ``delegate_to_{name}``
    tools and routes MCP calls to the appropriate MCPServerStreamableHTTP.
    Here it delegates to in-process ``MockSubAgent`` objects so the demo runs
    standalone.

    The ``call_tool`` signature is identical to the production class and
    already satisfies ``ToolsetProtocol``.
    """

    def __init__(self, sub_agents: Dict[str, MockSubAgent]) -> None:
        self._agents = sub_agents
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        self.calls.append({"tool": name, "args": dict(tool_args)})

        if name.startswith("delegate_to_"):
            agent_name = name[len("delegate_to_"):]
            if agent_name not in self._agents:
                raise ValueError(f"Unknown sub-agent: {agent_name!r}")
            task = tool_args.get("task", "")
            return await self._agents[agent_name].process_message(task, {})

        # MCP tool passthrough (echo in demo)
        return {"tool": name, "args": tool_args, "status": "ok"}


# ---------------------------------------------------------------------------
# Escalation handler — in production, page on-call / open ticket / push to SQS
# ---------------------------------------------------------------------------


_escalation_log: List[Dict[str, Any]] = []


async def kaos_escalation_handler(record: TraceRecord, ctx: Dict[str, Any]) -> None:
    ec = ctx.get("execution_context")
    if isinstance(ec, ExecutionContext):
        agent_id = ec.agent_id
    elif isinstance(ec, dict):
        agent_id = ec.get("agent_id", "unknown")
    else:
        agent_id = "unknown"
    entry = {
        "constraint_id": record.constraint_id,
        "tool": record.tool,
        "point": record.point.value,
        "action_id": record.action_id,
        "agent": agent_id,
    }
    _escalation_log.append(entry)
    print(
        f"  [ESCALATION] constraint={record.constraint_id} "
        f"tool={record.tool} agent={entry['agent']}"
    )


# ---------------------------------------------------------------------------
# Constraint spec
# ---------------------------------------------------------------------------


def _block_unknown_agent(ctx: Dict[str, Any]) -> bool:
    """Block delegation to any agent not in the KAOS agentNetwork.access list."""
    name = ctx["tool"]
    if not name.startswith("delegate_to_"):
        return False
    agent = name[len("delegate_to_"):]
    allowed = ctx["args"].get("_allowed_agents", ["finance_agent", "data_agent"])
    return agent not in allowed


def _block_high_value_action(ctx: Dict[str, Any]) -> bool:
    """Block any tool call that carries an amount >= $50,000."""
    amount = ctx["args"].get("amount", 0)
    try:
        return float(amount) >= 50_000
    except (TypeError, ValueError):
        return False


def _escalate_cross_tenant(ctx: Dict[str, Any]) -> bool:
    """Escalate tool calls that reference a tenant_id different from the caller."""
    ec = ctx.get("execution_context")
    if ec is None:
        return False
    caller_tenant = ec.tenant_id if isinstance(ec, ExecutionContext) else ec.get("tenant_id", "")
    target_tenant = ctx["args"].get("tenant_id", caller_tenant)
    return bool(caller_tenant) and target_tenant != caller_tenant


def _flag_slow_tool(ctx: Dict[str, Any]) -> bool:
    """Soft flag: log any tool call that took longer than 2 seconds (ATM)."""
    return ctx.get("elapsed", 0) > 2.0


SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="block_unknown_agent",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_block_unknown_agent,
            description="Block delegation to agents not in agentNetwork.access.",
        ),
        Constraint(
            id="block_high_value_action",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_block_high_value_action,
            description="Block any tool call carrying amount >= $50,000.",
        ),
        Constraint(
            id="escalate_cross_tenant",
            klass="escalation",
            verif="PAG",
            response="escalate",
            predicate=_escalate_cross_tenant,
            description="Escalate cross-tenant tool calls for human review.",
        ),
        Constraint(
            id="flag_slow_tool",
            klass="soft",
            verif="PAA",
            response="throttle_log",
            predicate=_flag_slow_tool,
            description="Log tool calls that exceeded 2-second SLA.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Build the governed toolset
# ---------------------------------------------------------------------------


def build_governed_toolset(
    sub_agents: Dict[str, MockSubAgent],
    memory: PAISMemory,
) -> GovernanceToolset:
    """Wire GovernanceToolset around KAOSDelegationToolset.

    In a real PAIS deployment, call this once during server startup and pass
    the result wherever PAIS currently instantiates DelegationToolset.

    The ``context_getter`` builds an ``ExecutionContext`` from the AgentDeps
    PAIS attaches to every Pydantic AI RunContext, giving SARC the full
    identity bag (agent name, tenant, session, roles) for trace attribution
    and predicate evaluation.
    """

    def context_getter(ctx: Any) -> Optional[ExecutionContext]:
        deps = getattr(ctx, "deps", None)
        if not isinstance(deps, AgentDeps):
            return None
        return ExecutionContext(
            agent_id=deps.agent_name,
            tenant_id=deps.tenant_id,
            session_id=deps.session_id,
            roles=deps.roles,
            environment="production",
        )

    return GovernanceToolset(
        wrapped=KAOSDelegationToolset(sub_agents),
        spec=SPEC,
        router=EscalationRouter(handler=kaos_escalation_handler),
        # memory_getter / session_id_getter are NOT needed here because
        # GovernanceToolset auto-detects ctx.deps.memory / ctx.deps.session_id
        # — exactly the shape PAIS produces.
        context_getter=context_getter,
    )


# ---------------------------------------------------------------------------
# Demo — six tool calls that exercise every constraint branch
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    label: str
    tool: str
    args: Dict[str, Any]
    tenant_id: str = "tenant-acme"


SCENARIOS = [
    Scenario(
        label="Allowed delegation to finance_agent",
        tool="delegate_to_finance_agent",
        args={"task": "generate Q1 report", "_allowed_agents": ["finance_agent", "data_agent"]},
    ),
    Scenario(
        label="Allowed MCP tool call (low value)",
        tool="erp.create_po",
        args={"vendor": "acme-supplies", "amount": 4_500},
    ),
    Scenario(
        label="BLOCKED — delegation to unknown agent",
        tool="delegate_to_shadow_agent",
        args={"task": "exfiltrate logs", "_allowed_agents": ["finance_agent", "data_agent"]},
    ),
    Scenario(
        label="BLOCKED — high-value purchase order",
        tool="erp.create_po",
        args={"vendor": "big-vendor", "amount": 75_000},
    ),
    Scenario(
        label="ESCALATED — cross-tenant data query",
        tool="db.query",
        args={"table": "customers", "tenant_id": "tenant-rival"},
        tenant_id="tenant-acme",
    ),
    Scenario(
        label="Allowed delegation to data_agent",
        tool="delegate_to_data_agent",
        args={"task": "summarise sales data", "_allowed_agents": ["finance_agent", "data_agent"]},
    ),
]


async def run_demo() -> None:
    memory = PAISMemory()
    session_id = str(uuid.uuid4())

    sub_agents = {
        "finance_agent": MockSubAgent("finance_agent"),
        "data_agent": MockSubAgent("data_agent"),
    }

    governed = build_governed_toolset(sub_agents, memory)

    print("=" * 65)
    print("KAOS PAIS × SARC Governance — Integration Demo")
    print("=" * 65)

    results: Dict[str, str] = {}

    for s in SCENARIOS:
        deps = AgentDeps(
            memory=memory,
            session_id=session_id,
            agent_name="coordinator-agent",
            tenant_id=s.tenant_id,
            roles=("agent",),
        )
        ctx = PAISContext(deps=deps)

        try:
            result = await governed.call_tool(s.tool, s.args, ctx=ctx, tool=None)
            status = "OK"
            detail = str(result)[:60]
        except ConstraintViolation as exc:
            status = "BLOCKED"
            detail = f"constraint={exc.constraint_id} at {exc.point.value}"

        results[s.label] = status
        tag = f"[{status}]".ljust(10)
        print(f"\n  {tag} {s.label}")
        print(f"           tool={s.tool}")
        print(f"           {detail}")

    print("\n" + "=" * 65)
    print(f"Scenarios run : {len(SCENARIOS)}")
    print(f"Allowed        : {sum(1 for v in results.values() if v == 'OK')}")
    print(f"Blocked        : {sum(1 for v in results.values() if v == 'BLOCKED')}")
    print(f"Escalations    : {len(_escalation_log)}")

    gov_events = memory.governance_events()
    print(f"Trace records  : {len(gov_events)} written to PAIS session memory")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_demo())
