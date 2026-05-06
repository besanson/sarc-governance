"""Tests for the tamper-evident hash chain."""

from __future__ import annotations

import pytest

from sarc_governance import (
    ChainError,
    append_record,
    canonical_event_hash,
    chain_records,
    verify_chain,
)
from sarc_governance.hashchain import GENESIS_PREV_HASH


def test_canonical_event_hash_is_deterministic():
    a = canonical_event_hash({"a": 1, "b": 2})
    b = canonical_event_hash({"b": 2, "a": 1})
    assert a == b


def test_canonical_event_hash_changes_with_content():
    a = canonical_event_hash({"a": 1})
    b = canonical_event_hash({"a": 2})
    assert a != b


def test_chain_records_round_trip():
    events = [{"id": i} for i in range(5)]
    chained = chain_records(events)
    assert len(chained) == 5
    assert chained[0]["prev_hash"] == GENESIS_PREV_HASH
    assert chained[1]["prev_hash"] == chained[0]["chain_hash"]
    assert verify_chain(chained) == []


def test_verify_chain_detects_payload_tampering():
    events = [{"id": i, "v": "before"} for i in range(3)]
    chained = chain_records(events)
    chained[1]["v"] = "tampered"
    breaks = verify_chain(chained)
    assert breaks
    # The tampered record's record_hash will mismatch.
    assert any(b.reason == "record_hash_mismatch" for b in breaks)


def test_verify_chain_detects_record_removal():
    events = [{"id": i} for i in range(3)]
    chained = chain_records(events)
    # Remove the middle record. Subsequent prev_hash will mismatch.
    del chained[1]
    breaks = verify_chain(chained)
    assert breaks
    assert any(b.reason == "prev_hash_mismatch" for b in breaks)


def test_verify_chain_detects_record_reorder():
    events = [{"id": i} for i in range(4)]
    chained = chain_records(events)
    chained[1], chained[2] = chained[2], chained[1]
    breaks = verify_chain(chained)
    assert breaks


def test_verify_chain_raises_when_requested():
    events = [{"id": 1}]
    chained = chain_records(events)
    chained[0]["chain_hash"] = "0" * 64  # corrupt
    with pytest.raises(ChainError):
        verify_chain(chained, raise_on_break=True)


def test_append_record_does_not_mutate_input():
    rec = {"id": 1}
    out = append_record(rec)
    assert "chain_hash" not in rec
    assert "chain_hash" in out


def test_verify_chain_detects_missing_chain_field():
    events = [{"id": i} for i in range(2)]
    chained = chain_records(events)
    del chained[0]["chain_hash"]
    breaks = verify_chain(chained)
    assert any(b.reason == "missing_field" for b in breaks)
