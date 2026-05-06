"""Tests for examples/human_escalation/run_demo.py."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

DEMO = (
    pathlib.Path(__file__).resolve().parent.parent
    / "examples"
    / "human_escalation"
    / "run_demo.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("human_escalation_demo", DEMO)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_module()


async def test_run_produces_expected_outcomes(demo):
    outcomes = await demo.run()
    assert len(outcomes) == 3

    approved, denied, timed_out = outcomes
    assert approved.blocked_by is None
    assert approved.review_decision == "approve"

    assert denied.blocked_by == "ch_blocked_unless_approved"
    assert denied.review_decision == "deny"

    assert timed_out.blocked_by == "ch_blocked_unless_approved"
    assert timed_out.review_decision == "timeout"


async def test_default_deny_when_no_decision_recorded(demo):
    """A request the reviewer never sees must default to deny."""
    ledger = demo.ApprovalLedger()
    spec = demo.build_spec(ledger)
    inner = demo.RefundToolset()
    governed = demo.GovernanceToolset(wrapped=inner, spec=spec)

    with pytest.raises(demo.ConstraintViolation) as excinfo:
        await governed.call_tool(
            "billing.refund", {"amount": 5_000, "request_id": "REQ-NO-REVIEW"}
        )
    assert excinfo.value.constraint_id == "ch_blocked_unless_approved"


async def test_low_value_refund_passes_without_review(demo):
    ledger = demo.ApprovalLedger()
    spec = demo.build_spec(ledger)
    inner = demo.RefundToolset()
    governed = demo.GovernanceToolset(wrapped=inner, spec=spec)

    result = await governed.call_tool(
        "billing.refund", {"amount": 25, "request_id": "REQ-LOW"}
    )
    assert result["status"] == "issued"
    assert ledger.decisions == {}
