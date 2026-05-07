#!/usr/bin/env python3
"""Procurement Agent demo — shows GovernanceToolset enforcing a SARC spec.

Run::

    python examples/procurement_agent/run_demo.py

What it does
------------
1. Loads ``sarc_spec.yaml`` with three procurement constraints.
2. Creates a mock ERP toolset that records calls and simulates a rolling
   spend ledger.
3. Wraps it with ``GovernanceToolset``.
4. Runs six representative purchase order scenarios (see ``SCENARIOS``).
5. Prints a per-scenario outcome and a final ``audit_trace`` summary.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sarc_governance import (
    GovernanceToolset,
    ConstraintViolation,
    EscalationRouter,
    TraceRecord,
    audit_trace,
    load_spec,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

SPEC_PATH = pathlib.Path(__file__).parent / "sarc_spec.yaml"


# ---------------------------------------------------------------------------
# In-memory session memory (no external dependency)
# ---------------------------------------------------------------------------


@dataclass
class _Session:
    session_id: str
    events: List[Dict[str, Any]] = field(default_factory=list)


class SimpleMemory:
    """Minimal in-process memory that satisfies MemoryProtocol."""

    def __init__(self) -> None:
        self._sessions: Dict[str, _Session] = {}

    def create_session(self, session_id: str) -> None:
        self._sessions[session_id] = _Session(session_id=session_id)

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        sess = self._sessions.get(session_id)
        if sess is None:
            return False
        sess.events.append({"event_type": event_type, "content": content})
        return True

    def governance_events(self, session_id: str) -> List[Dict[str, Any]]:
        sess = self._sessions.get(session_id)
        if sess is None:
            return []
        return [e["content"] for e in sess.events if e["event_type"] == "governance_event"]


# ---------------------------------------------------------------------------
# Mock ERP toolset
# ---------------------------------------------------------------------------


class ERPToolset:
    """Simulates an ERP system.  Tracks rolling spend across calls."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.rolling_24h_spend: float = 0.0

    async def call_tool(self, name: str, tool_args: Dict[str, Any], ctx: Any, tool: Any) -> Any:
        self.calls.append((name, dict(tool_args)))
        if name == "erp.create_po":
            amount = tool_args.get("amount", 0)
            self.rolling_24h_spend += amount
            return {
                "status": "created",
                "po_id": f"PO-{len(self.calls):04d}",
                "amount": amount,
                "rolling_24h_spend": self.rolling_24h_spend,
            }
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

SCENARIOS: List[Dict[str, Any]] = [
    {
        "label": "Small order — compliant",
        "tool": "erp.create_po",
        "args": {"amount": 5_000, "first_time_supplier": False},
    },
    {
        "label": "High-value order — PAG hard block",
        "tool": "erp.create_po",
        "args": {"amount": 75_000, "first_time_supplier": False},
    },
    {
        "label": "First-time supplier — PAG escalation block",
        "tool": "erp.create_po",
        "args": {"amount": 10_000, "first_time_supplier": True},
    },
    {
        "label": "Mid-size order pushing spend past threshold — PAA soft flag",
        "tool": "erp.create_po",
        # After the first compliant order (5 000) this pushes spend to 480 000.
        "args": {"amount": 475_000, "first_time_supplier": False},
    },
    {
        "label": "Tool other than erp.create_po — compliant",
        "tool": "erp.get_vendor",
        "args": {"vendor_id": "V-999"},
    },
    {
        "label": "High-value AND first-time supplier — PAG hard block wins",
        "tool": "erp.create_po",
        "args": {"amount": 100_000, "first_time_supplier": True},
    },
]


async def main() -> None:
    spec = load_spec(SPEC_PATH)
    erp = ERPToolset()
    memory = SimpleMemory()
    session_id = "demo-session"
    memory.create_session(session_id)

    routed_escalations: List[TraceRecord] = []

    async def escalation_handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        routed_escalations.append(rec)
        print(
            f"    [ER] Escalation routed: constraint={rec.constraint_id} "
            f"tool={rec.tool} action={rec.action_id}"
        )

    # Wire memory into the toolset via the memory_getter/session_id_getter hooks.
    toolset = GovernanceToolset(
        wrapped=erp,
        spec=spec,
        router=EscalationRouter(handler=escalation_handler),
        memory_getter=lambda _ctx: memory,
        session_id_getter=lambda _ctx: session_id,
    )

    print("=" * 60)
    print("SARC Procurement Agent Demo")
    print("=" * 60)

    for scenario in SCENARIOS:
        label = scenario["label"]
        tool = scenario["tool"]
        args = scenario["args"]
        print(f"\nScenario: {label}")
        print(f"  tool={tool!r}  args={args}")
        try:
            result = await toolset.call_tool(tool, args, ctx=None, tool=None)
            print(f"  → OK  result={result}")
        except ConstraintViolation as exc:
            print(f"  → BLOCKED  [{exc.constraint_id} at {exc.point.value}]")

    # ---- Audit -------------------------------------------------------
    print("\n" + "=" * 60)
    print("Audit summary")
    print("=" * 60)
    trace = memory.governance_events(session_id)
    print(f"Total trace records in memory: {len(trace)}")
    discrepancies = audit_trace(spec, trace)
    if discrepancies:
        print(f"Discrepancies ({len(discrepancies)}):")
        for d in discrepancies:
            print(
                f"  [{d['type']}] action={d['action_id']} constraint={d['constraint']}: {d['message']}"
            )
        print()
        print("Note: Coverage discrepancies on blocked actions are expected — when a hard")
        print("PAG constraint raises before dispatch, PAA constraints are never reached.")
        print("The audit correctly identifies these as incomplete traces.")
    else:
        print("No discrepancies — trace is SARC-conformant.")

    print(f"\nTotal escalations routed: {len(routed_escalations)}")
    print(f"ERP inner toolset invocations: {len(erp.calls)}")
    print(f"Final rolling spend: ${erp.rolling_24h_spend:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
