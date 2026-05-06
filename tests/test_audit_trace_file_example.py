"""Tests that the bundled audit trace files behave as documented."""

from __future__ import annotations

import json
import pathlib

from sarc_governance import audit_trace
from sarc_governance.specs import load_spec

EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / "examples" / "audit_trace_file"


def _spec():
    return load_spec(EXAMPLE / "spec.yaml")


def _trace(name: str):
    return json.loads((EXAMPLE / name).read_text())


def test_pass_trace_yields_no_discrepancies():
    discrepancies = audit_trace(_spec(), _trace("trace_pass.json"))
    assert discrepancies == []


def test_fail_trace_reports_placement_response_and_coverage():
    discrepancies = audit_trace(_spec(), _trace("trace_fail.json"))
    types = sorted({d["type"] for d in discrepancies})
    assert types == ["coverage", "placement", "response"]


def test_fail_trace_response_message_names_constraint():
    discrepancies = audit_trace(_spec(), _trace("trace_fail.json"))
    response_records = [d for d in discrepancies if d["type"] == "response"]
    assert len(response_records) == 1
    assert response_records[0]["constraint"] == "ch_high_value_po"
