"""Tests for the policy lifecycle module."""

from __future__ import annotations

import pytest

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    PolicyMetadata,
    diff_policies,
    inspect_policy,
    policy_checksum,
)


def _spec(*entries):
    return ConstraintSpec(constraints=list(entries))


def _c(cid, klass="hard", verif="PAG", response="block", pred=None, desc=""):
    return Constraint(
        id=cid,
        klass=klass,
        verif=verif,
        response=response,
        predicate=pred or (lambda ctx: False),
        description=desc,
    )


def test_checksum_is_stable_for_same_spec():
    a = _spec(_c("c1"))
    b = _spec(_c("c1"))
    assert policy_checksum(a) == policy_checksum(b)


def test_checksum_changes_when_constraint_added():
    a = _spec(_c("c1"))
    b = _spec(_c("c1"), _c("c2"))
    assert policy_checksum(a) != policy_checksum(b)


def test_checksum_independent_of_constraint_order():
    a = _spec(_c("c1"), _c("c2"))
    b = _spec(_c("c2"), _c("c1"))
    assert policy_checksum(a) == policy_checksum(b)


def test_checksum_changes_when_response_changes():
    a = _spec(_c("c1", response="block"))
    b = _spec(_c("c1", response="block_or_escalate"))
    assert policy_checksum(a) != policy_checksum(b)


def test_inspect_policy_counts_and_lists():
    spec = _spec(
        _c("c1"),
        _c("c2", klass="escalation", verif="PAG", response="escalate"),
        _c("c3", klass="soft", verif="PAA", response="log"),
    )
    summary = inspect_policy(spec)
    assert summary["constraint_count"] == 3
    assert summary["by_class"] == {"escalation": 1, "hard": 1, "soft": 1}
    assert summary["by_point"] == {"PAA": 1, "PAG": 2}
    assert len(summary["constraints"]) == 3
    assert summary["checksum"] == policy_checksum(spec)


def test_inspect_policy_includes_metadata_when_provided():
    meta = PolicyMetadata(policy_id="p1", version="1.0.0", approval_status="approved")
    summary = inspect_policy(_spec(_c("c1")), metadata=meta)
    assert summary["metadata"]["approval_status"] == "approved"
    assert summary["metadata"]["version"] == "1.0.0"


def test_diff_policies_added_removed_unchanged_changed():
    old = _spec(_c("c1"), _c("c2"), _c("c3"))
    new = _spec(_c("c1", response="block_or_escalate"), _c("c3"), _c("c4"))
    d = diff_policies(old, new)
    assert [c["id"] for c in d["added"]] == ["c4"]
    assert [c["id"] for c in d["removed"]] == ["c2"]
    assert [c["id"] for c in d["changed"]] == ["c1"]
    assert d["unchanged"] == ["c3"]
    assert "response" in d["changed"][0]["fields"]
    assert d["checksum"]["equal"] is False


def test_diff_policies_equal_specs():
    s = _spec(_c("c1"), _c("c2"))
    d = diff_policies(s, s)
    assert d["added"] == []
    assert d["removed"] == []
    assert d["changed"] == []
    assert d["unchanged"] == ["c1", "c2"]
    assert d["checksum"]["equal"] is True


def test_policy_metadata_rejects_invalid_status():
    with pytest.raises(ValueError):
        PolicyMetadata(approval_status="rubberstamped")
