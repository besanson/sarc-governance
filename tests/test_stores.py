"""Tests for the trace store backends."""

from __future__ import annotations

import json
import pathlib

import pytest

from sarc_governance import (
    ConstraintClass,
    EnforcementPoint,
    JSONLTraceStore,
    MemoryTraceStore,
    Response,
    SQLiteTraceStore,
    TraceRecord,
    verify_chain,
)


def _record(action_id="act-1", session_id=None):
    rec = TraceRecord(
        action_id=action_id,
        tool="erp.create_po",
        point=EnforcementPoint.PAG,
        constraint_id="ch_high_value_po",
        klass=ConstraintClass.HARD,
        fired=True,
        response=Response.BLOCK,
    )
    return rec


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_memory_store_round_trip():
    s = MemoryTraceStore()
    s.append(_record(), session_id="s1")
    s.append(_record(action_id="act-2"), session_id="s2")
    assert len(s) == 2
    assert len(s.list("s1")) == 1
    assert s.list("s1")[0]["action_id"] == "act-1"


def test_memory_store_export_jsonl(tmp_path):
    s = MemoryTraceStore()
    s.append(_record(), session_id="s1")
    out = tmp_path / "trace.jsonl"
    n = s.export_jsonl(out)
    assert n == 1
    line = out.read_text().strip()
    assert json.loads(line)["action_id"] == "act-1"


def test_memory_store_hash_chain():
    s = MemoryTraceStore(hash_chain=True)
    for i in range(3):
        s.append(_record(action_id=f"act-{i}"), session_id="s1")
    breaks = verify_chain(s.list())
    assert breaks == []


# ---------------------------------------------------------------------------
# JSONL
# ---------------------------------------------------------------------------


def test_jsonl_store_round_trip(tmp_path):
    path = tmp_path / "trace.jsonl"
    with JSONLTraceStore(path) as s:
        s.append(_record(), session_id="s1")
        s.append(_record(action_id="act-2"), session_id="s1")
    # Re-open and read.
    s2 = JSONLTraceStore(path)
    try:
        records = s2.list("s1")
    finally:
        s2.close()
    assert len(records) == 2


def test_jsonl_store_persists_across_process(tmp_path):
    path = tmp_path / "trace.jsonl"
    s1 = JSONLTraceStore(path, hash_chain=True)
    try:
        s1.append(_record(), session_id="s1")
        s1.append(_record(action_id="act-2"), session_id="s1")
    finally:
        s1.close()

    s2 = JSONLTraceStore(path, hash_chain=True)
    try:
        s2.append(_record(action_id="act-3"), session_id="s1")
        records = s2.list("s1")
    finally:
        s2.close()

    assert len(records) == 3
    # Chain still verifies.
    assert verify_chain(records) == []


def test_jsonl_store_skips_corrupted_lines(tmp_path):
    path = tmp_path / "trace.jsonl"
    s = JSONLTraceStore(path)
    try:
        s.append(_record(), session_id="s1")
    finally:
        s.close()
    # Append garbage.
    with path.open("a") as f:
        f.write("{not valid json\n")
        f.write("\n")
    s2 = JSONLTraceStore(path)
    try:
        records = s2.list()
    finally:
        s2.close()
    assert len(records) == 1


def test_jsonl_store_export(tmp_path):
    path = tmp_path / "trace.jsonl"
    out = tmp_path / "out.jsonl"
    with JSONLTraceStore(path) as s:
        s.append(_record(), session_id="s1")
        s.append(_record(action_id="act-2"), session_id="s2")
        n = s.export_jsonl(out, session_id="s1")
    assert n == 1


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def test_sqlite_store_round_trip(tmp_path):
    path = tmp_path / "trace.sqlite"
    s = SQLiteTraceStore(path)
    try:
        s.append(_record(), session_id="s1")
        s.append(_record(action_id="act-2"), session_id="s1")
        s.append(_record(action_id="act-3"), session_id="s2")
        assert len(s) == 3
        assert len(s.list("s1")) == 2
    finally:
        s.close()


def test_sqlite_store_persists_and_chain_continues(tmp_path):
    path = tmp_path / "trace.sqlite"
    s1 = SQLiteTraceStore(path, hash_chain=True)
    try:
        s1.append(_record(), session_id="s1")
        s1.append(_record(action_id="act-2"), session_id="s1")
    finally:
        s1.close()
    s2 = SQLiteTraceStore(path, hash_chain=True)
    try:
        s2.append(_record(action_id="act-3"), session_id="s1")
        records = s2.list()
    finally:
        s2.close()
    assert len(records) == 3
    assert verify_chain(records) == []


def test_sqlite_store_export_jsonl(tmp_path):
    path = tmp_path / "trace.sqlite"
    out = tmp_path / "out.jsonl"
    s = SQLiteTraceStore(path)
    try:
        s.append(_record(), session_id="s1")
        s.append(_record(action_id="act-2"), session_id="s2")
        n = s.export_jsonl(out, session_id="s1")
    finally:
        s.close()
    assert n == 1
    assert json.loads(out.read_text().strip())["action_id"] == "act-1"


def test_sqlite_in_memory():
    s = SQLiteTraceStore(":memory:")
    try:
        s.append(_record(), session_id="s1")
        assert len(s) == 1
    finally:
        s.close()


def test_sqlite_chain_break_detected_on_payload_tamper(tmp_path):
    """Editing payload directly in SQLite should trip verify_chain."""
    import sqlite3

    path = tmp_path / "trace.sqlite"
    s = SQLiteTraceStore(path, hash_chain=True)
    try:
        s.append(_record(), session_id="s1")
        s.append(_record(action_id="act-2"), session_id="s1")
    finally:
        s.close()

    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT id, payload FROM trace_records").fetchall()
        # Corrupt the payload of the first row but keep its chain fields.
        rid, payload = rows[0]
        rec = json.loads(payload)
        rec["tool"] = "tampered"
        conn.execute(
            "UPDATE trace_records SET payload = ? WHERE id = ?",
            (json.dumps(rec, sort_keys=True), rid),
        )
        conn.commit()
    finally:
        conn.close()

    s = SQLiteTraceStore(path)
    try:
        records = s.list()
    finally:
        s.close()
    breaks = verify_chain(records)
    assert breaks
