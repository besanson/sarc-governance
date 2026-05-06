#!/usr/bin/env python3
"""Human-in-the-loop escalation demo.

Demonstrates three outcomes for the same constraint:

- **approve** — the human reviewer approves the action; the inner toolset
  is then invoked.
- **deny**    — the reviewer denies; the action is blocked.
- **timeout** — the reviewer doesn't respond in time; default-deny.

The wiring keeps SARC honest about its role: the ``EscalationRouter`` only
*routes* — it never decides. A ``hard`` PAG constraint is the actual gate.
The pattern is: have a separate "needs_review" predicate fire ``escalation``
to notify a reviewer, and a paired ``hard`` predicate that blocks unless an
out-of-band approval has been recorded.

Run::

    python examples/human_escalation/run_demo.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    EscalationRouter,
    GovernanceToolset,
    TraceRecord,
)


# ---------------------------------------------------------------------------
# Approval ledger — the source of truth for "has a reviewer approved this?"
# ---------------------------------------------------------------------------


@dataclass
class ApprovalLedger:
    """Records reviewer decisions keyed by tool+request id."""

    decisions: Dict[str, str] = field(default_factory=dict)  # key -> approve/deny

    def key(self, tool: str, args: Dict[str, Any]) -> str:
        return f"{tool}:{args.get('request_id', '?')}"

    def decision(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        return self.decisions.get(self.key(tool, args))

    def record(self, tool: str, args: Dict[str, Any], outcome: str) -> None:
        self.decisions[self.key(tool, args)] = outcome


# ---------------------------------------------------------------------------
# Reviewer model — deterministic for tests
# ---------------------------------------------------------------------------


class DeterministicReviewer:
    """A scripted reviewer.

    Each entry in ``responses`` is one of ``"approve"``, ``"deny"``, or
    ``"timeout"`` and is consumed in order on each escalation event.
    """

    def __init__(self, responses: List[str], *, timeout_s: float = 0.2) -> None:
        self._responses = list(responses)
        self.timeout_s = timeout_s
        self.handled: List[Dict[str, Any]] = []

    async def review(self, ctx: Dict[str, Any]) -> str:
        if not self._responses:
            return "timeout"
        next_response = self._responses.pop(0)
        if next_response == "timeout":
            # Sleep past the deadline so wait_for cancels us.
            await asyncio.sleep(self.timeout_s * 5)
            return "timeout"
        # Real reviewer would block on user input; we just yield once.
        await asyncio.sleep(0)
        return next_response


# ---------------------------------------------------------------------------
# EscalationRouter handler — calls the reviewer and updates the ledger
# ---------------------------------------------------------------------------


def make_handler(
    reviewer: DeterministicReviewer,
    ledger: ApprovalLedger,
) -> Any:
    async def handler(record: TraceRecord, ctx: Dict[str, Any]) -> None:
        # Only the escalation event needs reviewer involvement; the paired
        # hard constraint also flows through the router but must not consume
        # another reviewer response.
        if record.constraint_id != "ce_needs_review":
            return
        try:
            outcome = await asyncio.wait_for(
                reviewer.review(ctx), timeout=reviewer.timeout_s
            )
        except asyncio.TimeoutError:
            outcome = "timeout"
        reviewer.handled.append(
            {
                "constraint": record.constraint_id,
                "action": record.action_id,
                "tool": record.tool,
                "outcome": outcome,
            }
        )
        ledger.record(record.tool, ctx.get("args", {}), outcome)

    return handler


# ---------------------------------------------------------------------------
# Toolset and spec
# ---------------------------------------------------------------------------


class RefundToolset:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        self.calls.append({"tool": name, "args": dict(tool_args)})
        return {"status": "issued", "amount": tool_args.get("amount", 0)}


def build_spec(ledger: ApprovalLedger) -> ConstraintSpec:
    """Two constraints that together implement gated approval.

    1. ``ce_needs_review`` (escalation/PAG) — fires for any high-value refund
       and routes the action to the reviewer via the EscalationRouter.
    2. ``ch_blocked_unless_approved`` (hard/PAG) — blocks the same action
       unless the ledger records an explicit ``"approve"`` decision.
    """

    def needs_review(ctx: Dict[str, Any]) -> bool:
        return (
            ctx["tool"] == "billing.refund"
            and ctx["args"].get("amount", 0) >= 1_000
        )

    def blocked_unless_approved(ctx: Dict[str, Any]) -> bool:
        if not needs_review(ctx):
            return False
        return ledger.decision(ctx["tool"], ctx["args"]) != "approve"

    return ConstraintSpec(
        constraints=[
            Constraint(
                id="ce_needs_review",
                klass="escalation",
                verif="PAG",
                response="escalate",
                predicate=needs_review,
                description="Route high-value refunds to a human reviewer.",
            ),
            Constraint(
                id="ch_blocked_unless_approved",
                klass="hard",
                verif="PAG",
                response="block_or_escalate",
                predicate=blocked_unless_approved,
                description="Block high-value refund unless ledger has an approval.",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    label: str
    request_id: str
    blocked_by: Optional[str]
    review_decision: Optional[str]


async def run() -> List[Outcome]:
    """Run three scenarios — approve, deny, timeout — and return outcomes."""
    ledger = ApprovalLedger()
    reviewer = DeterministicReviewer(
        responses=["approve", "deny", "timeout"], timeout_s=0.05
    )
    inner = RefundToolset()
    spec = build_spec(ledger)
    router = EscalationRouter(handler=make_handler(reviewer, ledger))
    governed = GovernanceToolset(wrapped=inner, spec=spec, router=router)

    scenarios = [
        ("Approved refund", "REQ-100"),
        ("Denied refund", "REQ-101"),
        ("Timed-out refund (default-deny)", "REQ-102"),
    ]

    outcomes: List[Outcome] = []
    for label, request_id in scenarios:
        args = {"amount": 5_000, "request_id": request_id}
        try:
            await governed.call_tool("billing.refund", args)
            blocked_by = None
        except ConstraintViolation as exc:
            blocked_by = exc.constraint_id
        outcomes.append(
            Outcome(
                label=label,
                request_id=request_id,
                blocked_by=blocked_by,
                review_decision=ledger.decision("billing.refund", args),
            )
        )

    return outcomes


def _print(outcomes: List[Outcome]) -> None:
    print("=" * 60)
    print("Human-in-the-Loop Escalation Demo")
    print("=" * 60)
    for o in outcomes:
        verdict = "EXECUTED" if o.blocked_by is None else f"BLOCKED ({o.blocked_by})"
        print(
            f"  {o.label:<35} review={o.review_decision or '<none>':<8} -> {verdict}"
        )
    print()
    print(
        "Note: the EscalationRouter only routes — the ledger + a paired hard\n"
        "PAG constraint are what actually gate execution."
    )


async def main() -> None:
    outcomes = await run()
    _print(outcomes)


if __name__ == "__main__":
    asyncio.run(main())
