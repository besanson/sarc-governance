#!/usr/bin/env python3
"""KAOS-shaped adapter demo for ``GovernanceToolset``.

Run::

    python examples/kaos_style_adapter/run_demo.py

What it shows
-------------
KAOS / pydantic-ai expose tool dispatch through an ``AbstractToolset`` whose
``call_tool`` signature is::

    async def call_tool(name, tool_args, ctx, tool) -> Any

and where ``ctx`` is a ``RunContext`` carrying agent-level dependencies on
``ctx.deps`` (typically including a session memory and a session id).

``GovernanceToolset`` already speaks that shape. This demo builds a tiny
fake of it — a ``RunContext`` dataclass with a ``deps`` attribute exposing
``memory`` (a ``MemoryProtocol``-compliant in-process store) and
``session_id`` — and shows that:

1. Wrapping a KAOS-shaped toolset requires zero adapter code.
2. ``GovernanceToolset`` auto-detects ``ctx.deps.memory`` and
   ``ctx.deps.session_id`` and persists every ``TraceRecord`` there.
3. The recorded trace audits cleanly against the spec.

No KAOS or pydantic-ai dependency is involved.  Everything runs in-process.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sarc_kaos import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    GovernanceToolset,
    TraceRecord,
    audit_trace,
)


# ---------------------------------------------------------------------------
# Fake KAOS-shaped session memory (satisfies MemoryProtocol structurally)
# ---------------------------------------------------------------------------


class InProcessMemory:
    """Mimics a KAOS session memory backed by an in-process dict."""

    def __init__(self) -> None:
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    def open(self, session_id: str) -> None:
        self._events.setdefault(session_id, [])

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self._events.setdefault(session_id, []).append(
            {"event_type": event_type, "content": content, "metadata": metadata or {}}
        )
        return True

    def governance_events(self, session_id: str) -> List[Dict[str, Any]]:
        return [
            e["content"]
            for e in self._events.get(session_id, [])
            if e["event_type"] == "governance_event"
        ]


# ---------------------------------------------------------------------------
# Fake KAOS-shaped agent deps + run context
# ---------------------------------------------------------------------------


@dataclass
class AgentDeps:
    """Stand-in for a KAOS / pydantic-ai ``AgentDeps`` dataclass."""

    memory: InProcessMemory
    session_id: str
    actor: str = "agent-0"


@dataclass
class RunContext:
    """Stand-in for a KAOS / pydantic-ai ``RunContext[AgentDeps]``."""

    deps: AgentDeps
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# A KAOS-shaped toolset.  Note the signature matches AbstractToolset.call_tool.
# ---------------------------------------------------------------------------


class CustomerToolset:
    """Mock customer-service toolset.

    Two tools:

    - ``crm.lookup_account`` — read-only.
    - ``crm.issue_refund`` — refunds; subject to a high-value cap.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        self.calls.append({"tool": name, "args": dict(tool_args), "actor": getattr(ctx.deps, "actor", "?")})
        if name == "crm.lookup_account":
            return {"account_id": tool_args["account_id"], "tier": "gold"}
        if name == "crm.issue_refund":
            return {
                "status": "issued",
                "refund_id": f"R-{len(self.calls):04d}",
                "amount": tool_args.get("amount", 0),
            }
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Spec — refund cap and a soft post-action audit on amount.
# ---------------------------------------------------------------------------


def _is_large_refund(ctx: Dict[str, Any]) -> bool:
    return ctx["tool"] == "crm.issue_refund" and ctx["args"].get("amount", 0) >= 1_000


def _result_amount_over_500(ctx: Dict[str, Any]) -> bool:
    result = ctx.get("result") or {}
    return isinstance(result, dict) and result.get("amount", 0) >= 500


SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="ch_refund_cap",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_is_large_refund,
            description="Block refunds >= $1,000 before dispatch.",
        ),
        Constraint(
            id="cs_refund_audit",
            klass="soft",
            verif="PAA",
            response="throttle_log",
            predicate=_result_amount_over_500,
            description="Flag refunds >= $500 for post-action review.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


SCENARIOS = [
    {"label": "Account lookup — read-only, no constraints", "tool": "crm.lookup_account",
     "args": {"account_id": "A-100"}},
    {"label": "Small refund — compliant", "tool": "crm.issue_refund",
     "args": {"account_id": "A-100", "amount": 250}},
    {"label": "Mid refund — soft PAA flag", "tool": "crm.issue_refund",
     "args": {"account_id": "A-100", "amount": 750}},
    {"label": "Large refund — hard PAG block", "tool": "crm.issue_refund",
     "args": {"account_id": "A-100", "amount": 5_000}},
]


async def run() -> Dict[str, Any]:
    """Run all scenarios and return a structured summary (used by tests)."""
    memory = InProcessMemory()
    session_id = "kaos-demo-session"
    memory.open(session_id)

    deps = AgentDeps(memory=memory, session_id=session_id, actor="agent-0")
    ctx = RunContext(deps=deps)

    inner = CustomerToolset()

    # No memory_getter / session_id_getter — auto-detection handles ctx.deps.
    governed = GovernanceToolset(wrapped=inner, spec=SPEC)

    outcomes: List[Dict[str, Any]] = []
    for scenario in SCENARIOS:
        try:
            result = await governed.call_tool(
                scenario["tool"],
                scenario["args"],
                ctx=ctx,
                tool=None,
            )
            outcomes.append({"label": scenario["label"], "ok": True, "result": result})
        except ConstraintViolation as exc:
            outcomes.append(
                {
                    "label": scenario["label"],
                    "ok": False,
                    "blocked_by": exc.constraint_id,
                    "point": exc.point.value,
                }
            )

    trace = memory.governance_events(session_id)
    discrepancies = audit_trace(SPEC, trace)

    return {
        "outcomes": outcomes,
        "trace": trace,
        "discrepancies": discrepancies,
        "inner_calls": inner.calls,
    }


def _print_summary(summary: Dict[str, Any]) -> None:
    print("=" * 60)
    print("KAOS-style Adapter Demo")
    print("=" * 60)
    print()
    print("Wiring:")
    print("  RunContext(deps=AgentDeps(memory=InProcessMemory, session_id=...))")
    print("  -> passed as ctx to GovernanceToolset.call_tool")
    print("  -> trace records auto-persisted via ctx.deps.memory.add_event")
    print()
    for outcome in summary["outcomes"]:
        print(f"Scenario: {outcome['label']}")
        if outcome["ok"]:
            print(f"  → OK  result={outcome['result']}")
        else:
            print(f"  → BLOCKED  [{outcome['blocked_by']} at {outcome['point']}]")
    print()
    print("=" * 60)
    print("Trace persisted on ctx.deps.memory")
    print("=" * 60)
    print(f"Total governance events recorded: {len(summary['trace'])}")
    if summary["discrepancies"]:
        print(f"Audit discrepancies: {len(summary['discrepancies'])}")
        for d in summary["discrepancies"]:
            print(f"  [{d['type']}] action={d['action_id']} "
                  f"constraint={d['constraint']}: {d['message']}")
        print()
        print("Note: coverage discrepancies on hard-blocked actions are expected —")
        print("PAA never runs when PAG raises.")
    else:
        print("No audit discrepancies — trace is SARC-conformant.")
    print(f"\nInner toolset invocations: {len(summary['inner_calls'])}")


async def main() -> None:
    summary = await run()
    _print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
