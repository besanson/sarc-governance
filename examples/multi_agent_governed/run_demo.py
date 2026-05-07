#!/usr/bin/env python3
"""Two governed agents chained — end-to-end expense approval pipeline.

This example shows ``GovernanceToolset`` applied at two levels in a
multi-agent chain: a coordinator agent and a validator agent, each with
their own independent ``ConstraintSpec``.  Constraints fire at both levels;
a block at the validator propagates back through the coordinator.

Architecture
------------

    Caller
      │
      ▼
    coordinator_governed  (CoordinatorSpec)
      │  PAG: block ERP submit if validator rejected
      │  PAG: block ERP submit if daily spend > $5 000
      │
      ├─── small expense ──► erp.submit_expense   (direct, no validation)
      │
      └─── large expense ──► delegate.validate_expense
                                    │
                                    ▼
                             validator_governed  (ValidatorSpec)
                               │  PAG: block if vendor is blacklisted
                               │  ESCALATION/PAG: escalate if amount > $2 000
                               │  SOFT/PAA: flag duplicate expense

Each agent has its own session memory and trace log.  The coordinator reads
the validator's result and uses it to decide whether to forward the expense
to the ERP.

Run::

    python examples/multi_agent_governed/run_demo.py
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    EscalationRouter,
    GovernanceToolset,
    TraceRecord,
)
from sarc_governance.context import ExecutionContext


# ---------------------------------------------------------------------------
# In-process session memory (satisfies MemoryProtocol)
# ---------------------------------------------------------------------------


class SimpleMemory:
    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._events.append(
            {"session_id": session_id, "event_type": event_type, "content": content}
        )

    def governance_events(self) -> List[Dict[str, Any]]:
        return [e["content"] for e in self._events if e["event_type"] == "governance_event"]


@dataclass
class Deps:
    """Holds memory + session_id in the shape GovernanceToolset auto-detects."""

    memory: SimpleMemory
    session_id: str
    agent_name: str


@dataclass
class Ctx:
    deps: Deps


# ---------------------------------------------------------------------------
# Validator agent — inner toolset
# ---------------------------------------------------------------------------

BLACKLISTED_VENDORS = {"shadow-corp", "off-books-llc"}


class ValidatorToolset:
    """Inner toolset for the validator agent.

    Exposes one tool: ``expense.validate``.
    Returns ``{"approved": bool, "reason": str}``.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(self, name: str, args: Dict[str, Any], ctx: Any, tool: Any) -> Any:
        self.calls.append({"tool": name, "args": dict(args)})
        if name != "expense.validate":
            raise ValueError(f"unknown tool: {name!r}")
        amount = float(args.get("amount", 0))
        # Simple approval logic (real agent would call an LLM here)
        if amount > 1_500:
            return {
                "approved": False,
                "reason": f"amount ${amount:,.0f} exceeds validator limit",
            }
        return {"approved": True, "reason": "within policy"}


# ---------------------------------------------------------------------------
# Coordinator agent — inner toolset (delegates to validator_governed)
# ---------------------------------------------------------------------------


class CoordinatorToolset:
    """Inner toolset for the coordinator agent.

    Exposes two tools:
    - ``erp.submit_expense`` — submit directly to ERP (small amounts)
    - ``delegate.validate_expense`` — call the validator agent first
    """

    def __init__(self, validator_governed: GovernanceToolset) -> None:
        self._validator = validator_governed
        self.calls: List[Dict[str, Any]] = []
        self._daily_spend: float = 0.0

    async def call_tool(self, name: str, args: Dict[str, Any], ctx: Any, tool: Any) -> Any:
        self.calls.append({"tool": name, "args": dict(args)})

        if name == "erp.submit_expense":
            self._daily_spend += float(args.get("amount", 0))
            return {
                "submitted": True,
                "expense_id": str(uuid.uuid4())[:8],
                "daily_total": self._daily_spend,
            }

        if name == "delegate.validate_expense":
            # Build a context for the validator agent with its own session
            validator_deps = Deps(
                memory=SimpleMemory(),
                session_id="validator-" + str(uuid.uuid4())[:8],
                agent_name="validator-agent",
            )
            validator_ctx = Ctx(deps=validator_deps)
            # ConstraintViolation from the validator propagates up to the coordinator
            return await self._validator.call_tool(
                "expense.validate", args, ctx=validator_ctx, tool=None
            )

        raise ValueError(f"unknown tool: {name!r}")

    @property
    def daily_spend(self) -> float:
        return self._daily_spend


# ---------------------------------------------------------------------------
# Constraint specs
# ---------------------------------------------------------------------------


# --- ValidatorSpec ---


def _block_blacklisted_vendor(ctx: Dict[str, Any]) -> bool:
    return ctx["args"].get("vendor", "").lower() in BLACKLISTED_VENDORS


def _escalate_large_amount(ctx: Dict[str, Any]) -> bool:
    try:
        return float(ctx["args"].get("amount", 0)) > 2_000
    except (TypeError, ValueError):
        return False


def _flag_duplicate_expense(ctx: Dict[str, Any]) -> bool:
    result = ctx.get("result", {})
    return bool(result.get("duplicate"))


VALIDATOR_SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="block_blacklisted_vendor",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_block_blacklisted_vendor,
            description="Block validation for vendors on the blacklist.",
        ),
        Constraint(
            id="escalate_large_expense",
            klass="escalation",
            verif="PAG",
            response="escalate",
            predicate=_escalate_large_amount,
            description="Escalate expenses over $2,000 for human review.",
        ),
        Constraint(
            id="flag_duplicate_expense",
            klass="soft",
            verif="PAA",
            response="throttle_log",
            predicate=_flag_duplicate_expense,
            description="Flag duplicate expense submissions.",
        ),
    ]
)


# --- CoordinatorSpec ---


def _block_rejected_expense(ctx: Dict[str, Any]) -> bool:
    if ctx["tool"] != "erp.submit_expense":
        return False
    result = ctx["args"].get("_validation_result", {})
    return result.get("approved") is False


def _block_daily_limit_exceeded(ctx: Dict[str, Any]) -> bool:
    if ctx["tool"] != "erp.submit_expense":
        return False
    daily = float(ctx["args"].get("_daily_spend", 0))
    amount = float(ctx["args"].get("amount", 0))
    return (daily + amount) > 5_000


COORDINATOR_SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="block_rejected_expense",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_block_rejected_expense,
            description="Block ERP submission if validator returned approved=False.",
        ),
        Constraint(
            id="block_daily_limit",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_block_daily_limit_exceeded,
            description="Block ERP submission if daily spend would exceed $5,000.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Escalation tracking
# ---------------------------------------------------------------------------

_escalations: List[Dict[str, Any]] = []


async def _escalation_handler(record: TraceRecord, ctx: Dict[str, Any]) -> None:
    _escalations.append(
        {
            "constraint": record.constraint_id,
            "tool": record.tool,
            "agent": (ctx.get("execution_context") or {}).get("agent_id", "?")
            if isinstance(ctx.get("execution_context"), dict)
            else getattr(ctx.get("execution_context"), "agent_id", "?"),
        }
    )


# ---------------------------------------------------------------------------
# Build the two governed toolsets
# ---------------------------------------------------------------------------


def build_pipeline() -> Tuple[GovernanceToolset, CoordinatorToolset, ValidatorToolset]:
    validator_inner = ValidatorToolset()
    validator_governed = GovernanceToolset(
        wrapped=validator_inner,
        spec=VALIDATOR_SPEC,
        router=EscalationRouter(handler=_escalation_handler),
        context_getter=lambda ctx: ExecutionContext(
            agent_id=getattr(getattr(ctx, "deps", None), "agent_name", "validator-agent"),
        ),
    )

    coordinator_inner = CoordinatorToolset(validator_governed=validator_governed)
    coordinator_governed = GovernanceToolset(
        wrapped=coordinator_inner,
        spec=COORDINATOR_SPEC,
        router=EscalationRouter(handler=_escalation_handler),
        context_getter=lambda ctx: ExecutionContext(
            agent_id=getattr(getattr(ctx, "deps", None), "agent_name", "coordinator-agent"),
        ),
    )

    return coordinator_governed, coordinator_inner, validator_inner


# ---------------------------------------------------------------------------
# Helper: submit an expense through the full pipeline
# ---------------------------------------------------------------------------


async def submit_expense(
    coordinator: GovernanceToolset,
    coordinator_inner: CoordinatorToolset,
    memory: SimpleMemory,
    session_id: str,
    vendor: str,
    amount: float,
    *,
    description: str = "",
) -> Dict[str, Any]:
    """Submit an expense through the coordinator agent.

    For amounts >= $500, the coordinator first calls delegate.validate_expense;
    if the validator approves, it then calls erp.submit_expense.
    If either step is blocked by governance, ConstraintViolation is raised.
    """
    ctx = Ctx(deps=Deps(memory=memory, session_id=session_id, agent_name="coordinator-agent"))

    if amount >= 500:
        # Step 1 — delegate to validator
        validation = await coordinator.call_tool(
            "delegate.validate_expense",
            {"vendor": vendor, "amount": amount},
            ctx=ctx,
            tool=None,
        )
        # Step 2 — submit to ERP only if validator approved
        result = await coordinator.call_tool(
            "erp.submit_expense",
            {
                "vendor": vendor,
                "amount": amount,
                "_validation_result": validation,
                "_daily_spend": coordinator_inner.daily_spend,
            },
            ctx=ctx,
            tool=None,
        )
        return {"validation": validation, "submission": result}
    else:
        result = await coordinator.call_tool(
            "erp.submit_expense",
            {
                "vendor": vendor,
                "amount": amount,
                "_daily_spend": coordinator_inner.daily_spend,
            },
            ctx=ctx,
            tool=None,
        )
        return {"submission": result}


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    label: str
    vendor: str
    amount: float
    expect: str  # "ok" | "blocked_at_validator" | "blocked_at_coordinator"
    expect_escalation: bool = False


SCENARIOS: List[Scenario] = [
    Scenario(
        label="Small expense — direct ERP submit, no validation",
        vendor="office-supplies-co",
        amount=150.0,
        expect="ok",
    ),
    Scenario(
        label="Large expense — validator approves, ERP submit succeeds",
        vendor="cloud-vendor",
        amount=800.0,
        expect="ok",
    ),
    Scenario(
        label="Very large expense — escalated at validator, but still within limit",
        vendor="consulting-firm",
        amount=2_500.0,
        expect="blocked_at_validator",  # validator returns approved=False for >$1,500
        expect_escalation=True,
    ),
    Scenario(
        label="Blacklisted vendor — blocked at validator before any check",
        vendor="shadow-corp",
        amount=600.0,
        expect="blocked_at_validator",
    ),
    Scenario(
        label="Daily spend limit — blocked at coordinator after prior approvals",
        vendor="office-supplies-co",
        # Previous ok submissions: $150 + $800 = $950; this tips over $5,000
        amount=4_200.0,
        expect="blocked_at_coordinator",
        expect_escalation=True,  # >$2,000 triggers escalation at validator first
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run() -> None:
    coordinator, coordinator_inner, validator_inner = build_pipeline()
    memory = SimpleMemory()
    session_id = str(uuid.uuid4())

    print("=" * 65)
    print("Multi-agent governed pipeline — expense approval")
    print("Coordinator spec: 2 constraints | Validator spec: 3 constraints")
    print("=" * 65)

    results: List[Dict[str, Any]] = []
    esc_before = 0

    for s in SCENARIOS:
        esc_before = len(_escalations)
        outcome: Dict[str, Any] = {
            "scenario": s.label,
            "vendor": s.vendor,
            "amount": s.amount,
        }
        try:
            data = await submit_expense(
                coordinator,
                coordinator_inner,
                memory,
                session_id,
                vendor=s.vendor,
                amount=s.amount,
            )
            outcome["status"] = "ok"
            outcome["data"] = data
        except ConstraintViolation as exc:
            outcome["status"] = "blocked"
            outcome["constraint_id"] = exc.constraint_id
            outcome["point"] = exc.point.value

        escalated_this = len(_escalations) > esc_before
        tag = f"[{outcome['status'].upper()}]".ljust(10)
        esc_tag = " +ESCALATION" if escalated_this else ""
        print(f"\n  {tag} {s.label}")
        print(f"           vendor={s.vendor}  amount=${s.amount:,.0f}{esc_tag}")
        if outcome["status"] == "blocked":
            print(f"           constraint={outcome['constraint_id']} at {outcome['point']}")

        # Assertions — verify the scenario landed where expected
        if s.expect == "ok":
            assert outcome["status"] == "ok", f"expected OK, got {outcome}"
        elif s.expect == "blocked_at_validator":
            assert outcome["status"] == "blocked", f"expected BLOCKED, got {outcome}"
        elif s.expect == "blocked_at_coordinator":
            assert outcome["status"] == "blocked", f"expected BLOCKED, got {outcome}"
        if s.expect_escalation:
            assert escalated_this, f"expected escalation for scenario: {s.label}"

        results.append(outcome)

    coord_events = memory.governance_events()

    print("\n" + "=" * 65)
    print(f"Scenarios         : {len(SCENARIOS)}")
    print(f"Passed            : {sum(1 for r in results if r['status'] == 'ok')}")
    print(f"Blocked           : {sum(1 for r in results if r['status'] == 'blocked')}")
    print(f"Escalations       : {len(_escalations)}")
    print(f"Coordinator traces: {len(coord_events)} records in session memory")
    print(f"Validator inner calls: {len(validator_inner.calls)}")
    print(f"Coordinator inner calls: {len(coordinator_inner.calls)}")
    print("All assertions passed.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run())
