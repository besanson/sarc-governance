#!/usr/bin/env python3
"""Runnable example for the KAOS PAIS × SARC Governance adapter.

This file lets you verify the adapter end-to-end without a running KAOS
cluster.  It provides stand-ins for the three KAOS/PAIS types the adapter
needs — ``DelegationToolset``, ``Memory``, and ``AgentDeps`` — and drives six
realistic tool-call scenarios through the adapter.

To run:

    python examples/kaos_pais_adapter/run_demo.py

For a real KAOS deployment, ignore this file and use ``adapter.py`` directly.
See the docstring in ``adapter.py`` for the four-line integration recipe.

Stand-in vs. real types
-----------------------
The stand-ins below mirror the public signatures of their PAIS counterparts:

    Stand-in class          Real PAIS class
    -------------------     ----------------------------
    PAISMemory              pais.memory.LocalMemory
    KAOSDelegationToolset   pais.tools.DelegationToolset
    AgentDeps               pais.serverutils.AgentDeps (RunContext[AgentDeps])
    PAISContext             pydantic_ai.RunContext[AgentDeps]

Swapping stand-ins for the real classes requires no changes to adapter.py.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sarc_governance import Constraint, ConstraintSpec, ConstraintViolation
from sarc_governance.context import ExecutionContext
from sarc_governance.trace import TraceRecord

from examples.kaos_pais_adapter.adapter import build_governed_toolset


# ---------------------------------------------------------------------------
# Stand-ins for KAOS PAIS types (pais.memory, pais.tools, pais.serverutils)
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

    Identical ``add_event`` signature — satisfies ``MemoryProtocol`` and the
    real class would too, with no code changes.
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
    """Stand-in for the deps object on pydantic_ai.RunContext[AgentDeps].

    GovernanceToolset auto-detects ``ctx.deps.memory`` and
    ``ctx.deps.session_id``, so no extra wiring is needed.
    """

    memory: PAISMemory
    session_id: str
    tenant_id: str = ""
    roles: tuple = ()


@dataclass
class PAISContext:
    """Stand-in for pydantic_ai.RunContext[AgentDeps]."""

    deps: AgentDeps


class MockSubAgent:
    """Stand-in for pais.serverutils.RemoteAgent.

    In production this calls POST /v1/chat/completions on the target agent pod.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    async def process_message(self, task: str, context: Dict[str, Any]) -> str:
        return f"{self.name} completed: {task}"


class KAOSDelegationToolset:
    """Stand-in for pais.tools.DelegationToolset.

    The real class exposes registered sub-agents as ``delegate_to_{name}``
    tools and routes MCP calls to the appropriate MCPServerStreamableHTTP.
    The ``call_tool`` signature is identical, so GovernanceToolset wraps both
    without modification.
    """

    def __init__(self, sub_agents: Dict[str, MockSubAgent]) -> None:
        self._agents = sub_agents

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        if name.startswith("delegate_to_"):
            agent_name = name[len("delegate_to_"):]
            if agent_name not in self._agents:
                raise ValueError(f"Unknown sub-agent: {agent_name!r}")
            return await self._agents[agent_name].process_message(
                tool_args.get("task", ""), {}
            )
        return {"tool": name, "args": tool_args, "status": "ok"}


# ---------------------------------------------------------------------------
# Constraint spec — load from YAML in production; inline here for the example
# ---------------------------------------------------------------------------


def _block_unknown_agent(ctx: Dict[str, Any]) -> bool:
    name = ctx["tool"]
    if not name.startswith("delegate_to_"):
        return False
    agent = name[len("delegate_to_"):]
    allowed = ctx["args"].get("_allowed_agents", [])
    return agent not in allowed


def _block_high_value_action(ctx: Dict[str, Any]) -> bool:
    try:
        return float(ctx["args"].get("amount", 0)) >= 50_000
    except (TypeError, ValueError):
        return False


def _escalate_cross_tenant(ctx: Dict[str, Any]) -> bool:
    ec = ctx.get("execution_context")
    if ec is None:
        return False
    caller = ec.tenant_id if isinstance(ec, ExecutionContext) else ec.get("tenant_id", "")
    target = ctx["args"].get("tenant_id", caller)
    return bool(caller) and target != caller


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
    ]
)

# ---------------------------------------------------------------------------
# Escalation handler — replace with queue / ticketing / paging in production
# ---------------------------------------------------------------------------

_escalation_log: List[Dict[str, Any]] = []


async def _escalation_handler(record: TraceRecord, ctx: Dict[str, Any]) -> None:
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
        f"tool={record.tool} agent={agent_id}"
    )


# ---------------------------------------------------------------------------
# Scenarios
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
        args={"task": "generate Q1 report",
              "_allowed_agents": ["finance_agent", "data_agent"]},
    ),
    Scenario(
        label="Allowed MCP tool call (low value)",
        tool="erp.create_po",
        args={"vendor": "acme-supplies", "amount": 4_500},
    ),
    Scenario(
        label="BLOCKED — delegation to unknown agent",
        tool="delegate_to_shadow_agent",
        args={"task": "exfiltrate logs",
              "_allowed_agents": ["finance_agent", "data_agent"]},
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
        args={"task": "summarise sales data",
              "_allowed_agents": ["finance_agent", "data_agent"]},
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run() -> None:
    memory = PAISMemory()
    session_id = str(uuid.uuid4())

    sub_agents = {
        "finance_agent": MockSubAgent("finance_agent"),
        "data_agent": MockSubAgent("data_agent"),
    }

    # This is the real adapter call — identical to what a KAOS deployment does.
    governed = build_governed_toolset(
        delegation_toolset=KAOSDelegationToolset(sub_agents),
        agent_name="coordinator-agent",
        spec=SPEC,
        tenant_id="tenant-acme",
        roles=("agent",),
        escalation_handler=_escalation_handler,
    )

    print("=" * 65)
    print("KAOS PAIS × SARC Governance — integration example")
    print("=" * 65)

    ok = blocked = 0

    for s in SCENARIOS:
        deps = AgentDeps(
            memory=memory,
            session_id=session_id,
            tenant_id=s.tenant_id,
            roles=("agent",),
        )
        ctx = PAISContext(deps=deps)

        try:
            result = await governed.call_tool(s.tool, s.args, ctx=ctx, tool=None)
            tag, detail = "OK", str(result)[:60]
            ok += 1
        except ConstraintViolation as exc:
            tag = "BLOCKED"
            detail = f"constraint={exc.constraint_id} at {exc.point.value}"
            blocked += 1

        print(f"\n  [{tag}]".ljust(13) + s.label)
        print(f"           tool={s.tool}")
        print(f"           {detail}")

    gov_events = memory.governance_events()
    print("\n" + "=" * 65)
    print(f"Scenarios     : {len(SCENARIOS)}")
    print(f"Allowed       : {ok}")
    print(f"Blocked       : {blocked}")
    print(f"Escalations   : {len(_escalation_log)}")
    print(f"Trace records : {len(gov_events)} written to PAIS session memory")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run())
