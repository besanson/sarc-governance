"""CLI tests for the new policy/trace subcommands."""

from __future__ import annotations

import io
import json
import pathlib
from contextlib import redirect_stderr, redirect_stdout


from sarc_governance.cli import main
from sarc_governance import (
    SQLiteTraceStore,
    chain_records,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC_PROC = REPO_ROOT / "examples" / "procurement_agent" / "sarc_spec.yaml"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# policy inspect
# ---------------------------------------------------------------------------


def test_policy_inspect_text():
    rc, out, _ = _run(["policy", "inspect", str(SPEC_PROC)])
    assert rc == 0
    assert "checksum:" in out
    assert "constraints: 3" in out
    assert "ch_high_value_po" in out


def test_policy_inspect_json():
    rc, out, _ = _run(["policy", "inspect", str(SPEC_PROC), "--json"])
    assert rc == 0
    data = json.loads(out)
    assert data["constraint_count"] == 3
    assert isinstance(data["checksum"], str) and len(data["checksum"]) == 64


def test_policy_inspect_missing_returns_2(tmp_path):
    rc, _, err = _run(["policy", "inspect", str(tmp_path / "nope.yaml")])
    assert rc == 2
    assert "not found" in err.lower()


# ---------------------------------------------------------------------------
# policy diff
# ---------------------------------------------------------------------------


def _write_spec(path: pathlib.Path, response: str = "block") -> None:
    path.write_text(
        "constraints:\n"
        "  - id: ch_high_value_po\n"
        "    class: hard\n"
        "    verif: PAG\n"
        f"    response: {response}\n"
        "    predicate: is_high_value_po\n",
        encoding="utf-8",
    )


def test_policy_diff_no_changes(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    _write_spec(a)
    _write_spec(b)
    rc, out, _ = _run(["policy", "diff", str(a), str(b)])
    assert rc == 0
    assert "+0" in out and "-0" in out and "~0" in out


def test_policy_diff_change_response(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    _write_spec(a, response="block")
    _write_spec(b, response="block_or_escalate")
    rc, out, _ = _run(["policy", "diff", str(a), str(b)])
    assert rc == 0
    assert "changed:" in out
    assert "ch_high_value_po" in out


def test_policy_diff_exit_code_flag(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    _write_spec(a, response="block")
    _write_spec(b, response="block_or_escalate")
    rc, _, _ = _run(["policy", "diff", str(a), str(b), "--exit-code"])
    assert rc == 1


def test_policy_diff_json(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    _write_spec(a, response="block")
    _write_spec(b, response="block_or_escalate")
    rc, out, _ = _run(["policy", "diff", str(a), str(b), "--json"])
    assert rc == 0
    data = json.loads(out)
    assert data["checksum"]["equal"] is False
    assert len(data["changed"]) == 1


# ---------------------------------------------------------------------------
# trace verify-chain
# ---------------------------------------------------------------------------


def test_trace_verify_chain_jsonl_ok(tmp_path):
    chained = chain_records([{"i": i} for i in range(3)])
    path = tmp_path / "trace.jsonl"
    with path.open("w") as f:
        for r in chained:
            f.write(json.dumps(r) + "\n")
    rc, out, _ = _run(["trace", "verify-chain", str(path)])
    assert rc == 0
    assert "OK" in out


def test_trace_verify_chain_jsonl_broken(tmp_path):
    chained = chain_records([{"i": i} for i in range(3)])
    chained[1]["i"] = 999  # tamper
    path = tmp_path / "trace.jsonl"
    with path.open("w") as f:
        for r in chained:
            f.write(json.dumps(r) + "\n")
    rc, out, _ = _run(["trace", "verify-chain", str(path)])
    assert rc == 1
    assert "BROKEN" in out


def test_trace_verify_chain_json_list_ok(tmp_path):
    chained = chain_records([{"i": i} for i in range(2)])
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(chained))
    rc, out, _ = _run(["trace", "verify-chain", str(path)])
    assert rc == 0


def test_trace_verify_chain_missing_file(tmp_path):
    rc, _, err = _run(["trace", "verify-chain", str(tmp_path / "nope.jsonl")])
    assert rc == 2
    assert "not found" in err.lower()


def test_trace_verify_chain_invalid_json(tmp_path):
    path = tmp_path / "trace.json"
    path.write_text("{not json")
    rc, _, err = _run(["trace", "verify-chain", str(path)])
    assert rc == 1


# ---------------------------------------------------------------------------
# trace export
# ---------------------------------------------------------------------------


def test_trace_export_from_sqlite(tmp_path):
    from sarc_governance import (
        ConstraintClass,
        EnforcementPoint,
        Response,
        TraceRecord,
    )

    store_path = tmp_path / "trace.sqlite"
    s = SQLiteTraceStore(store_path)
    try:
        rec = TraceRecord(
            action_id="act-1",
            tool="t",
            point=EnforcementPoint.PAG,
            constraint_id="c1",
            klass=ConstraintClass.HARD,
            fired=False,
            response=Response.BLOCK,
        )
        s.append(rec, session_id="s1")
    finally:
        s.close()

    out = tmp_path / "out.jsonl"
    rc, stdout, _ = _run(["trace", "export", str(store_path), str(out)])
    assert rc == 0
    assert "1 record" in stdout
    line = out.read_text().strip()
    assert json.loads(line)["action_id"] == "act-1"


def test_trace_export_missing_store(tmp_path):
    rc, _, err = _run(
        ["trace", "export", str(tmp_path / "nope.sqlite"), str(tmp_path / "out.jsonl")]
    )
    assert rc == 2
    assert "not found" in err.lower()
