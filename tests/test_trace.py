"""Tests for trace.py — TraceRecord serialisation and ActionEvent."""

from __future__ import annotations


from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response
from sarc_governance.trace import ActionEvent, TraceRecord, new_action_id


def _rec(**kwargs) -> TraceRecord:
    defaults = dict(
        action_id="a1",
        tool="t",
        point=EnforcementPoint.PAG,
        constraint_id="c1",
        klass=ConstraintClass.HARD,
        fired=True,
        response=Response.BLOCK,
    )
    defaults.update(kwargs)
    return TraceRecord(**defaults)


def test_trace_record_to_dict():
    rec = _rec()
    d = rec.to_dict()
    assert d["action_id"] == "a1"
    assert d["point"] == "PAG"
    assert d["class"] == "hard"
    assert d["fired"] is True
    assert d["response"] == "block"
    assert "extra" not in d  # omitted when empty


def test_trace_record_to_dict_with_extra():
    rec = _rec(extra={"elapsed": 0.05})
    d = rec.to_dict()
    assert d["extra"] == {"elapsed": 0.05}


def test_trace_record_roundtrip():
    rec = _rec(
        point=EnforcementPoint.PAA,
        klass=ConstraintClass.SOFT,
        fired=False,
        response=Response.THROTTLE_LOG,
        extra={"custom": 42},
    )
    d = rec.to_dict()
    rec2 = TraceRecord.from_dict(d)
    assert rec2.action_id == rec.action_id
    assert rec2.point is EnforcementPoint.PAA
    assert rec2.klass is ConstraintClass.SOFT
    assert rec2.fired is False
    assert rec2.response is Response.THROTTLE_LOG
    assert rec2.extra == {"custom": 42}


def test_new_action_id_unique():
    ids = {new_action_id() for _ in range(100)}
    assert len(ids) == 100


def test_action_event_fired_constraints():
    r1 = _rec(constraint_id="c1", fired=True)
    r2 = _rec(constraint_id="c2", fired=False)
    ev = ActionEvent(action_id="a1", tool="t", args={}, records=[r1, r2])
    assert ev.fired_constraints == ["c1"]


def test_action_event_evaluated_ids():
    r1 = _rec(constraint_id="c1")
    r2 = _rec(constraint_id="c2")
    ev = ActionEvent(action_id="a1", tool="t", args={}, records=[r1, r2])
    assert ev.evaluated_constraint_ids == {"c1", "c2"}
