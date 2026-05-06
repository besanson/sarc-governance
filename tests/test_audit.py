"""Tests for audit.py — audit_trace coverage/placement/response/attribution."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from sarc_kaos import audit_trace
from sarc_kaos.constraints import (
    Constraint,
    ConstraintClass,
    ConstraintSpec,
    EnforcementPoint,
    Response,
)


# ---------------------------------------------------------------------------
# Helpers to build trace records in the flat (GovernanceToolset native) format
# ---------------------------------------------------------------------------


def _flat_rec(
    action_id: str,
    constraint_id: str,
    point: str,
    klass: str,
    fired: bool,
    response: str,
) -> Dict[str, Any]:
    return {
        "action_id": action_id,
        "tool": "t",
        "point": point,
        "constraint_id": constraint_id,
        "class": klass,
        "fired": fired,
        "response": response,
        "timestamp": 0.0,
    }


def _make_spec(*args) -> ConstraintSpec:
    return ConstraintSpec(constraints=list(args))


def _c(cid: str, klass: ConstraintClass, verif: EnforcementPoint, resp: Response) -> Constraint:
    return Constraint(id=cid, klass=klass, verif=verif, response=resp, predicate=lambda _: True)


# ---------------------------------------------------------------------------
# Coverage discrepancies
# ---------------------------------------------------------------------------


def test_coverage_missing_constraint():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
        _c("c2", ConstraintClass.SOFT, EnforcementPoint.PAA, Response.THROTTLE_LOG),
    )
    # Trace has only c1; c2 is missing for action a1.
    trace = [_flat_rec("a1", "c1", "PAG", "hard", False, "block")]
    discrepancies = audit_trace(spec, trace)
    coverage = [d for d in discrepancies if d["type"] == "coverage"]
    assert len(coverage) == 1
    assert coverage[0]["constraint"] == "c2"
    assert coverage[0]["action_id"] == "a1"


def test_coverage_unknown_constraint_in_trace():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    trace = [
        _flat_rec("a1", "c1", "PAG", "hard", False, "block"),
        _flat_rec("a1", "ghost", "PAG", "hard", False, "block"),  # not in spec
    ]
    discrepancies = audit_trace(spec, trace)
    coverage = [d for d in discrepancies if d["type"] == "coverage"]
    assert any(d["constraint"] == "ghost" for d in coverage)


def test_no_discrepancies_when_trace_is_conformant():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
        _c("c2", ConstraintClass.SOFT, EnforcementPoint.PAA, Response.THROTTLE_LOG),
    )
    trace = [
        _flat_rec("a1", "c1", "PAG", "hard", False, "block"),
        _flat_rec("a1", "c2", "PAA", "soft", False, "throttle_log"),
    ]
    assert audit_trace(spec, trace) == []


# ---------------------------------------------------------------------------
# Placement discrepancies
# ---------------------------------------------------------------------------


def test_placement_hard_at_paa():
    """Hard constraint evaluated only at PAA → placement discrepancy."""
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    trace = [_flat_rec("a1", "c1", "PAA", "hard", False, "block")]
    discrepancies = audit_trace(spec, trace)
    placement = [d for d in discrepancies if d["type"] == "placement"]
    assert len(placement) == 1
    assert placement[0]["constraint"] == "c1"


def test_placement_soft_at_pag():
    spec = _make_spec(
        _c("cs", ConstraintClass.SOFT, EnforcementPoint.PAA, Response.THROTTLE_LOG),
    )
    trace = [_flat_rec("a1", "cs", "PAG", "soft", False, "throttle_log")]
    discrepancies = audit_trace(spec, trace)
    placement = [d for d in discrepancies if d["type"] == "placement"]
    assert len(placement) == 1


def test_no_placement_discrepancy_for_correct_point():
    spec = _make_spec(
        _c("c1", ConstraintClass.ESCALATION, EnforcementPoint.PAG, Response.ESCALATE),
    )
    trace = [_flat_rec("a1", "c1", "PAG", "escalation", True, "escalate")]
    discrepancies = audit_trace(spec, trace)
    placement = [d for d in discrepancies if d["type"] == "placement"]
    assert placement == []


# ---------------------------------------------------------------------------
# Response discrepancies
# ---------------------------------------------------------------------------


def test_response_mismatch_when_fired():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    trace = [_flat_rec("a1", "c1", "PAG", "hard", True, "throttle_log")]  # wrong response
    discrepancies = audit_trace(spec, trace)
    response_disc = [d for d in discrepancies if d["type"] == "response"]
    assert len(response_disc) == 1
    assert "throttle_log" in response_disc[0]["message"]
    assert "block" in response_disc[0]["message"]


def test_no_response_discrepancy_when_not_fired():
    """If fired=False, response mismatch should not be flagged."""
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    trace = [_flat_rec("a1", "c1", "PAG", "hard", False, "throttle_log")]
    discrepancies = audit_trace(spec, trace)
    response_disc = [d for d in discrepancies if d["type"] == "response"]
    assert response_disc == []


def test_no_response_discrepancy_when_correct():
    spec = _make_spec(
        _c("c1", ConstraintClass.SOFT, EnforcementPoint.PAA, Response.THROTTLE_LOG),
    )
    trace = [_flat_rec("a1", "c1", "PAA", "soft", True, "throttle_log")]
    discrepancies = audit_trace(spec, trace)
    assert [d for d in discrepancies if d["type"] == "response"] == []


# ---------------------------------------------------------------------------
# Attribution discrepancies (action-level trace only)
# ---------------------------------------------------------------------------


def test_attribution_empty_authority_flagged():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    # Action-level trace schema
    trace: List[Dict[str, Any]] = [
        {
            "action_id": "a1",
            "state": {},
            "action": {"tool": "t"},
            "evaluated": [{"id": "c1", "verif": "PAG", "fired": False, "response": "block"}],
            "attribution": {"authority_nonempty": False},  # bad
        }
    ]
    discrepancies = audit_trace(spec, trace, check_attribution=True)
    attribution = [d for d in discrepancies if d["type"] == "attribution"]
    assert len(attribution) == 1


def test_attribution_disabled_does_not_flag():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    trace: List[Dict[str, Any]] = [
        {
            "action_id": "a1",
            "state": {},
            "action": {"tool": "t"},
            "evaluated": [{"id": "c1", "verif": "PAG", "fired": False, "response": "block"}],
            "attribution": {"authority_nonempty": False},
        }
    ]
    discrepancies = audit_trace(spec, trace, check_attribution=False)
    attribution = [d for d in discrepancies if d["type"] == "attribution"]
    assert attribution == []


# ---------------------------------------------------------------------------
# Empty trace
# ---------------------------------------------------------------------------


def test_empty_trace_returns_no_discrepancies():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
    )
    assert audit_trace(spec, []) == []


# ---------------------------------------------------------------------------
# Multiple actions
# ---------------------------------------------------------------------------


def test_multiple_actions_each_checked_independently():
    spec = _make_spec(
        _c("c1", ConstraintClass.HARD, EnforcementPoint.PAG, Response.BLOCK),
        _c("c2", ConstraintClass.SOFT, EnforcementPoint.PAA, Response.THROTTLE_LOG),
    )
    # a1: has both constraints → conformant
    # a2: missing c2 → coverage discrepancy
    trace = [
        _flat_rec("a1", "c1", "PAG", "hard", False, "block"),
        _flat_rec("a1", "c2", "PAA", "soft", False, "throttle_log"),
        _flat_rec("a2", "c1", "PAG", "hard", False, "block"),
        # c2 missing for a2
    ]
    discrepancies = audit_trace(spec, trace)
    coverage = [d for d in discrepancies if d["type"] == "coverage"]
    assert len(coverage) == 1
    assert coverage[0]["action_id"] == "a2"
    assert coverage[0]["constraint"] == "c2"
