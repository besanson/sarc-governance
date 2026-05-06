"""Smoke + behavior tests for examples/bedrock_action_group_adapter/run_demo.py."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

DEMO = (
    pathlib.Path(__file__).resolve().parent.parent
    / "examples"
    / "bedrock_action_group_adapter"
    / "run_demo.py"
)


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("bedrock_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_function_body(resp):
    return json.loads(
        resp["response"]["functionResponse"]["responseBody"]["TEXT"]["body"]
    )


def _decode_api_body(resp):
    return json.loads(
        resp["response"]["responseBody"]["application/json"]["body"]
    )


# ---------------------------------------------------------------------------
# Top-level demo run
# ---------------------------------------------------------------------------


async def test_demo_runs_and_returns_expected_envelope_shape(demo):
    summary = await demo.run()
    assert len(summary["responses"]) == 4
    for entry in summary["responses"]:
        env = entry["response"]
        assert env["messageVersion"] == "1.0"
        assert "response" in env
        assert "sessionAttributes" in env
        assert "promptSessionAttributes" in env


async def test_safe_action_invokes_inner_backend(demo):
    handler, inner, _memory = demo.make_handler()
    resp = await handler.handle(demo._safe_event())
    body = _decode_function_body(resp)
    assert body == {"account": "acct-A", "balance": 12_500}
    assert any(c["tool"] == "lookup_balance" for c in inner.calls)


async def test_blocked_high_risk_action_prevents_inner_call(demo):
    handler, inner, _memory = demo.make_handler()
    resp = await handler.handle(demo._large_transfer_event())
    body = _decode_function_body(resp)
    assert body["error"] == "blocked_by_governance"
    assert body["constraint_id"] == "ch_large_transfer"
    assert body["point"] == "PAG"
    # Inner backend must never have seen the blocked call.
    assert all(c["tool"] != "transfer_funds" for c in inner.calls), inner.calls


async def test_bedrock_response_envelope_for_function_schema(demo):
    handler, _inner, _memory = demo.make_handler()
    resp = await handler.handle(demo._safe_event())
    inner = resp["response"]
    assert inner["actionGroup"] == "PaymentActions"
    assert inner["function"] == "lookup_balance"
    assert "functionResponse" in inner
    assert "responseBody" in inner["functionResponse"]
    assert "TEXT" in inner["functionResponse"]["responseBody"]


async def test_bedrock_response_envelope_for_api_schema(demo):
    handler, _inner, _memory = demo.make_handler()
    resp = await handler.handle(demo._api_schema_event())
    inner = resp["response"]
    assert inner["actionGroup"] == "PaymentActions"
    assert inner["apiPath"] == "/balances/{account}"
    assert inner["httpMethod"] == "GET"
    assert inner["httpStatusCode"] == 200
    body = _decode_api_body(resp)
    assert body == {"account": "acct-A", "balance": 12_500}


async def test_soft_paa_constraint_is_logged_but_does_not_block(demo):
    handler, inner, memory = demo.make_handler()
    resp = await handler.handle(demo._mid_transfer_event())
    body = _decode_function_body(resp)
    assert body["status"] == "executed"
    assert body["amount"] == 2500
    assert any(c["tool"] == "transfer_funds" for c in inner.calls)

    trace = memory.governance_events("session-001")
    paa_records = [
        r for r in trace
        if r["constraint_id"] == "cs_mid_transfer_audit"
        and r["point"] == "PAA"
    ]
    assert len(paa_records) == 1
    assert paa_records[0]["fired"] is True
    assert paa_records[0]["class"] == "soft"


async def test_trace_records_persist_with_session_id(demo):
    handler, _inner, memory = demo.make_handler()
    await handler.handle(demo._safe_event())
    trace = memory.governance_events("session-001")
    # safe lookup has no PAG/PAA constraints applicable -> no records emitted.
    # The point of this test is the persistence wiring works on at least one
    # action that does emit; do a transfer too:
    await handler.handle(demo._mid_transfer_event())
    trace = memory.governance_events("session-001")
    assert len(trace) > 0
    for rec in trace:
        assert rec["action_id"].startswith("act-")
        assert rec["tool"] in {"lookup_balance", "transfer_funds"}


async def test_audit_discrepancies_only_for_blocked_action(demo):
    """The blocked action should trigger a coverage discrepancy on the soft
    PAA constraint (PAA never ran because PAG raised). Non-blocked actions
    should not contribute new discrepancies."""
    summary = await demo.run()
    discrepancies = summary["discrepancies"]
    # Each discrepancy should be tied to act-3 (the blocked transfer).
    assert all(d["action_id"] == "act-3" for d in discrepancies), discrepancies
    assert any(
        d["type"] == "coverage" and d["constraint"] == "cs_mid_transfer_audit"
        for d in discrepancies
    )


# ---------------------------------------------------------------------------
# normalize_event — both event shapes
# ---------------------------------------------------------------------------


def test_normalize_event_function_schema(demo):
    norm = demo.normalize_event(demo._mid_transfer_event())
    assert norm["name"] == "transfer_funds"
    assert norm["args"]["from"] == "acct-A"
    assert norm["args"]["to"] == "acct-B"
    assert norm["args"]["amount"] == 2500
    assert norm["session_id"] == "session-001"
    assert norm["action_group"] == "PaymentActions"


def test_normalize_event_api_schema(demo):
    norm = demo.normalize_event(demo._api_schema_event())
    assert norm["name"] == "GET /balances/{account}"
    assert norm["args"]["account"] == "acct-A"
    assert norm["session_id"] == "session-001"


def test_normalize_event_rejects_malformed(demo):
    bad = {"messageVersion": "1.0", "actionGroup": "X", "sessionId": "s"}
    with pytest.raises(ValueError):
        demo.normalize_event(bad)
