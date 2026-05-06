"""Tests for the ``sarc-kaos`` CLI."""

from __future__ import annotations

import io
import json
import pathlib
from contextlib import redirect_stderr, redirect_stdout

import pytest

from sarc_kaos.cli import build_parser, main

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC_PROC = REPO_ROOT / "examples" / "procurement_agent" / "sarc_spec.yaml"
SPEC_AUDIT = REPO_ROOT / "examples" / "audit_trace_file" / "spec.yaml"
TRACE_PASS = REPO_ROOT / "examples" / "audit_trace_file" / "trace_pass.json"
TRACE_FAIL = REPO_ROOT / "examples" / "audit_trace_file" / "trace_fail.json"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# parser sanity
# ---------------------------------------------------------------------------


def test_parser_has_all_subcommands():
    parser = build_parser()
    sub_actions = [a for a in parser._actions if a.dest == "command"]
    assert sub_actions, "subparsers missing"
    choices = set(sub_actions[0].choices)
    assert {"validate", "list-predicates", "audit", "demo"} <= choices


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_procurement_spec_succeeds():
    rc, out, _ = _run(["validate", str(SPEC_PROC)])
    assert rc == 0, out
    assert "constraints: 3" in out
    assert "ch_high_value_po" in out
    assert "ce_first_time_supplier" in out
    assert "cs_rolling_spend" in out


def test_validate_missing_spec_returns_2(tmp_path):
    missing = tmp_path / "nope.yaml"
    rc, _, err = _run(["validate", str(missing)])
    assert rc == 2
    assert "not found" in err.lower()


def test_validate_unknown_predicate_returns_1(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "constraints:\n"
        "  - id: ch\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    response: block\n"
        "    predicate: not_a_real_predicate\n"
    )
    rc, _, err = _run(["validate", str(bad)])
    assert rc == 1
    assert "predicate" in err.lower()


# ---------------------------------------------------------------------------
# list-predicates
# ---------------------------------------------------------------------------


def test_list_predicates_default():
    rc, out, _ = _run(["list-predicates"])
    assert rc == 0
    for name in (
        "any",
        "never",
        "is_high_value_po",
        "is_first_time_supplier",
        "rolling_spend_over_threshold",
    ):
        assert name in out


def test_list_predicates_quiet():
    rc, out, _ = _run(["list-predicates", "-q"])
    assert rc == 0
    lines = [l for l in out.splitlines() if l.strip()]
    # No header line in quiet mode.
    assert all(" -- " not in l for l in lines)
    assert "is_high_value_po" in lines


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def test_audit_pass_trace_returns_zero():
    rc, out, _ = _run(["audit", str(SPEC_AUDIT), str(TRACE_PASS)])
    assert rc == 0, out
    assert "PASS" in out


def test_audit_fail_trace_returns_one():
    rc, out, _ = _run(["audit", str(SPEC_AUDIT), str(TRACE_FAIL)])
    assert rc == 1
    assert "FAIL" in out
    assert "placement" in out
    assert "response" in out
    assert "coverage" in out


def test_audit_fail_trace_with_allow_discrepancies_returns_zero():
    rc, out, _ = _run(
        ["audit", str(SPEC_AUDIT), str(TRACE_FAIL), "--allow-discrepancies"]
    )
    assert rc == 0
    assert "FAIL" in out  # still reported


def test_audit_missing_trace_returns_2(tmp_path):
    rc, _, err = _run(["audit", str(SPEC_AUDIT), str(tmp_path / "no.json")])
    assert rc == 2
    assert "not found" in err.lower()


def test_audit_invalid_trace_json_returns_1(tmp_path):
    bad = tmp_path / "trace.json"
    bad.write_text("{not valid json")
    rc, _, err = _run(["audit", str(SPEC_AUDIT), str(bad)])
    assert rc == 1
    assert "json" in err.lower()


def test_audit_non_list_trace_returns_1(tmp_path):
    bad = tmp_path / "trace.json"
    bad.write_text(json.dumps({"records": []}))
    rc, _, err = _run(["audit", str(SPEC_AUDIT), str(bad)])
    assert rc == 1
    assert "list" in err.lower()


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------


def test_demo_procurement_runs_to_completion():
    rc, out, _ = _run(["demo", "procurement"])
    assert rc == 0
    assert "SARC Procurement Agent Demo" in out
    assert "Audit summary" in out
