#!/usr/bin/env python3
"""AWS Bedrock Agent action-group adapter for SARC.

AWS Bedrock Agents dispatch tool calls to a Lambda action-group handler.
The Lambda receives a JSON event roughly shaped like::

    {
        "messageVersion": "1.0",
        "agent": {"name": "...", "id": "...", "alias": "...", "version": "..."},
        "actionGroup": "PaymentActions",
        "function": "transfer_funds",
        "parameters": [
            {"name": "from", "type": "string", "value": "acct-A"},
            {"name": "to",   "type": "string", "value": "acct-B"},
            {"name": "amount", "type": "number", "value": "250"}
        ],
        "sessionId": "...",
        "sessionAttributes": {"actor": "agent-0"},
        "promptSessionAttributes": {},
        "inputText": "..."
    }

and must return the action-group response shape::

    {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": "PaymentActions",
            "function": "transfer_funds",
            "functionResponse": {
                "responseBody": {"TEXT": {"body": "<json string>"}}
            }
        },
        "sessionAttributes": {...},
        "promptSessionAttributes": {...}
    }

This example shows how to slot ``GovernanceToolset`` *between* the Lambda
entry point and the actual downstream system. No ``boto3`` or AWS SDK is
involved — events are constructed by hand and the "Lambda" is just a
Python function.

**Bedrock does not call SARC, KAOS, or anything else for governance.** The
adapter pattern is identical to KAOS / LangGraph / OpenAI: normalize the
framework's tool-call event into ``(name, args)``, run it through SARC, and
serialize the result back into the framework's response shape.

Run::

    python examples/bedrock_action_group_adapter/run_demo.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sarc_kaos import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    EscalationRouter,
    GovernanceToolset,
    TraceRecord,
    audit_trace,
)


# ---------------------------------------------------------------------------
# In-process trace memory (satisfies MemoryProtocol structurally).
# ---------------------------------------------------------------------------


class InProcessMemory:
    """Mimics a session memory store keyed by ``sessionId``."""

    def __init__(self) -> None:
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self._events.setdefault(session_id, []).append(
            {"event_type": event_type, "content": content, "metadata": metadata or {}}
        )
        return True

    def governance_events(self, session_id: str) -> List[Dict[str, Any]]:
        return [
            e["content"]
            for e in self._events.get(session_id, [])
            if e["event_type"] == "governance_event"
        ]


# ---------------------------------------------------------------------------
# Inner toolset — what the action-group Lambda would actually call into.
# In a real Lambda this is where you'd talk to a payments service, an
# internal API, a database, etc.
# ---------------------------------------------------------------------------


class PaymentBackend:
    """Mock downstream payments system."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        self.calls.append({"tool": name, "args": dict(tool_args)})
        if name == "lookup_balance" or name == "GET /balances/{account}":
            return {"account": tool_args["account"], "balance": 12_500}
        if name == "transfer_funds":
            return {
                "from": tool_args["from"],
                "to": tool_args["to"],
                "amount": tool_args["amount"],
                "status": "executed",
                "txn_id": f"TXN-{len(self.calls):04d}",
            }
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Event normalization — Bedrock event -> (name, args, session_id, ctx).
# ---------------------------------------------------------------------------


@dataclass
class BedrockCallContext:
    """Context object passed as ``ctx`` into ``GovernanceToolset.call_tool``.

    Carries enough of the Bedrock event for predicates and trace persistence
    to use without leaking framework specifics elsewhere.
    """

    session_id: str
    action_group: str
    agent: Dict[str, Any]
    session_attributes: Dict[str, Any]
    prompt_session_attributes: Dict[str, Any]
    memory: Optional[InProcessMemory] = None


def _coerce_param(value: Any, type_hint: str) -> Any:
    """Bedrock parameter values arrive as strings with a type hint.

    We coerce the obvious cases (number, integer, boolean) and pass the
    rest through. Real handlers may want stricter validation; SARC stays
    out of that.
    """
    if type_hint in ("number", "integer"):
        try:
            return int(value) if type_hint == "integer" else float(value)
        except (TypeError, ValueError):
            return value
    if type_hint == "boolean":
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)
    return value


def normalize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a Bedrock action-group event into a SARC-friendly call.

    Returns a dict with ``name``, ``args``, ``session_id``, ``action_group``,
    ``agent``, ``session_attributes``, ``prompt_session_attributes``.

    Function-schema events use ``function`` + ``parameters``; OpenAPI-schema
    events use ``apiPath`` + ``httpMethod`` + ``requestBody``. We accept
    both.
    """
    action_group = event.get("actionGroup", "")
    session_id = event.get("sessionId", "")
    agent = event.get("agent", {}) or {}
    session_attrs = event.get("sessionAttributes", {}) or {}
    prompt_attrs = event.get("promptSessionAttributes", {}) or {}

    if "function" in event:
        # Function-schema action group.
        name = event["function"]
        args: Dict[str, Any] = {}
        for p in event.get("parameters", []) or []:
            args[p["name"]] = _coerce_param(p.get("value"), p.get("type", ""))
    elif "apiPath" in event:
        # OpenAPI-schema action group. We synthesize a tool name from the
        # method + path so the SARC spec can target it predictably.
        method = event.get("httpMethod", "POST").upper()
        api_path = event["apiPath"]
        name = f"{method} {api_path}"
        args = {}
        body = event.get("requestBody", {}) or {}
        # Bedrock nests body under
        # body["content"]["application/json"]["properties"] = [{name,type,value}, ...]
        content = body.get("content", {}) or {}
        for _media_type, media in content.items():
            for p in media.get("properties", []) or []:
                args[p["name"]] = _coerce_param(p.get("value"), p.get("type", ""))
    else:
        raise ValueError(
            "Bedrock event missing both 'function' and 'apiPath' — cannot "
            "determine which tool to invoke."
        )

    return {
        "name": name,
        "args": args,
        "session_id": session_id,
        "action_group": action_group,
        "agent": agent,
        "session_attributes": session_attrs,
        "prompt_session_attributes": prompt_attrs,
    }


# ---------------------------------------------------------------------------
# Response building — SARC result -> Bedrock action-group response shape.
# ---------------------------------------------------------------------------


def build_response(
    *,
    action_group: str,
    function_or_path: str,
    body: Any,
    session_attributes: Dict[str, Any],
    prompt_session_attributes: Dict[str, Any],
    is_api: bool = False,
    http_status: int = 200,
) -> Dict[str, Any]:
    """Build a Bedrock action-group response envelope.

    The function-schema and apiSchema response shapes differ slightly; we
    accept either. ``body`` is JSON-serialized into the ``TEXT`` body.
    """
    body_text = json.dumps(body)
    if is_api:
        method, _, path = function_or_path.partition(" ")
        response_inner: Dict[str, Any] = {
            "actionGroup": action_group,
            "apiPath": path,
            "httpMethod": method,
            "httpStatusCode": http_status,
            "responseBody": {"application/json": {"body": body_text}},
        }
    else:
        response_inner = {
            "actionGroup": action_group,
            "function": function_or_path,
            "functionResponse": {
                "responseBody": {"TEXT": {"body": body_text}},
            },
        }
    return {
        "messageVersion": "1.0",
        "response": response_inner,
        "sessionAttributes": session_attributes,
        "promptSessionAttributes": prompt_session_attributes,
    }


# ---------------------------------------------------------------------------
# Lambda-style handler that wraps a SARC GovernanceToolset.
# ---------------------------------------------------------------------------


@dataclass
class BedrockActionGroupHandler:
    """Stand-in for an AWS Lambda function that backs an action group.

    In real AWS, you would deploy this as the Lambda handler:

        def lambda_handler(event, context):
            return asyncio.run(handler.handle(event))

    The handler keeps the SARC layer between the Bedrock event and the
    downstream system. SARC never sees Bedrock — only ``(name, args)``.
    """

    governed: GovernanceToolset
    memory: InProcessMemory

    async def handle(self, event: Dict[str, Any]) -> Dict[str, Any]:
        norm = normalize_event(event)
        is_api = "apiPath" in event

        ctx = BedrockCallContext(
            session_id=norm["session_id"],
            action_group=norm["action_group"],
            agent=norm["agent"],
            session_attributes=dict(norm["session_attributes"]),
            prompt_session_attributes=dict(norm["prompt_session_attributes"]),
            memory=self.memory,
        )

        try:
            result = await self.governed.call_tool(
                norm["name"],
                norm["args"],
                ctx=ctx,
                tool=None,
            )
            body = result
            http_status = 200
        except ConstraintViolation as exc:
            body = {
                "error": "blocked_by_governance",
                "constraint_id": exc.constraint_id,
                "point": exc.point.value,
                "message": (
                    "Action blocked by SARC governance. The agent should "
                    "either route to a human reviewer or pick a different "
                    "course of action."
                ),
            }
            # 403 in API-schema; the function-schema case ignores http_status.
            http_status = 403

        return build_response(
            action_group=norm["action_group"],
            function_or_path=norm["name"],
            body=body,
            session_attributes=ctx.session_attributes,
            prompt_session_attributes=ctx.prompt_session_attributes,
            is_api=is_api,
            http_status=http_status,
        )


# ---------------------------------------------------------------------------
# Memory / session_id getters — extract from BedrockCallContext.
# ---------------------------------------------------------------------------


def _memory_getter(ctx: Any) -> Optional[InProcessMemory]:
    if isinstance(ctx, BedrockCallContext):
        return ctx.memory
    return None


def _session_id_getter(ctx: Any) -> str:
    if isinstance(ctx, BedrockCallContext):
        return ctx.session_id
    return ""


# ---------------------------------------------------------------------------
# Spec — block large transfers (hard/PAG); flag mid-size for review (soft/PAA).
# ---------------------------------------------------------------------------


def _is_large_transfer(ctx: Dict[str, Any]) -> bool:
    return (
        ctx["tool"] == "transfer_funds"
        and ctx["args"].get("amount", 0) >= 10_000
    )


def _is_mid_transfer(ctx: Dict[str, Any]) -> bool:
    result = ctx.get("result") or {}
    if not isinstance(result, dict):
        return False
    return (
        ctx["tool"] == "transfer_funds"
        and result.get("status") == "executed"
        and ctx["args"].get("amount", 0) >= 1_000
    )


SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="ch_large_transfer",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_is_large_transfer,
            description="Block fund transfers >= $10,000 before dispatch.",
        ),
        Constraint(
            id="cs_mid_transfer_audit",
            klass="soft",
            verif="PAA",
            response="throttle_log",
            predicate=_is_mid_transfer,
            description="Log mid-size transfers (>= $1,000) for post-action review.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Sample events — what Bedrock would deliver to the Lambda.
# ---------------------------------------------------------------------------


def _safe_event() -> Dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "agent": {"name": "PaymentsAgent", "id": "AG1", "alias": "live", "version": "1"},
        "actionGroup": "PaymentActions",
        "function": "lookup_balance",
        "parameters": [
            {"name": "account", "type": "string", "value": "acct-A"},
        ],
        "sessionId": "session-001",
        "sessionAttributes": {"actor": "agent-0"},
        "promptSessionAttributes": {},
        "inputText": "what is the balance of acct-A?",
    }


def _mid_transfer_event() -> Dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "agent": {"name": "PaymentsAgent", "id": "AG1", "alias": "live", "version": "1"},
        "actionGroup": "PaymentActions",
        "function": "transfer_funds",
        "parameters": [
            {"name": "from", "type": "string", "value": "acct-A"},
            {"name": "to", "type": "string", "value": "acct-B"},
            {"name": "amount", "type": "number", "value": "2500"},
        ],
        "sessionId": "session-001",
        "sessionAttributes": {"actor": "agent-0"},
        "promptSessionAttributes": {},
        "inputText": "transfer $2500 from A to B",
    }


def _large_transfer_event() -> Dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "agent": {"name": "PaymentsAgent", "id": "AG1", "alias": "live", "version": "1"},
        "actionGroup": "PaymentActions",
        "function": "transfer_funds",
        "parameters": [
            {"name": "from", "type": "string", "value": "acct-A"},
            {"name": "to", "type": "string", "value": "acct-Z"},
            {"name": "amount", "type": "number", "value": "50000"},
        ],
        "sessionId": "session-001",
        "sessionAttributes": {"actor": "agent-0"},
        "promptSessionAttributes": {},
        "inputText": "transfer $50000 from A to Z",
    }


def _api_schema_event() -> Dict[str, Any]:
    """Same call but using the OpenAPI-schema event shape."""
    return {
        "messageVersion": "1.0",
        "agent": {"name": "PaymentsAgent", "id": "AG1", "alias": "live", "version": "1"},
        "actionGroup": "PaymentActions",
        "apiPath": "/balances/{account}",
        "httpMethod": "GET",
        "parameters": [],
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "account", "type": "string", "value": "acct-A"},
                    ]
                }
            }
        },
        "sessionId": "session-001",
        "sessionAttributes": {"actor": "agent-0"},
        "promptSessionAttributes": {},
        "inputText": "what is the balance of acct-A?",
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def make_handler() -> "tuple[BedrockActionGroupHandler, PaymentBackend, InProcessMemory]":
    memory = InProcessMemory()
    inner = PaymentBackend()
    governed = GovernanceToolset(
        wrapped=inner,
        spec=SPEC,
        router=EscalationRouter(),
        memory_getter=_memory_getter,
        session_id_getter=_session_id_getter,
    )
    return BedrockActionGroupHandler(governed=governed, memory=memory), inner, memory


async def run() -> Dict[str, Any]:
    """Run all four scenarios and return a structured summary."""
    handler, inner, memory = make_handler()

    events = [
        ("safe lookup (function-schema)", _safe_event()),
        ("mid transfer — soft PAA flag", _mid_transfer_event()),
        ("large transfer — hard PAG block", _large_transfer_event()),
        ("safe lookup (api-schema)", _api_schema_event()),
    ]

    responses: List[Dict[str, Any]] = []
    for label, event in events:
        resp = await handler.handle(event)
        responses.append({"label": label, "response": resp})

    trace = memory.governance_events("session-001")
    discrepancies = audit_trace(SPEC, trace)

    return {
        "responses": responses,
        "trace": trace,
        "discrepancies": discrepancies,
        "inner_calls": inner.calls,
    }


def _decode_body(resp: Dict[str, Any]) -> Any:
    inner = resp["response"]
    if "functionResponse" in inner:
        text = inner["functionResponse"]["responseBody"]["TEXT"]["body"]
    else:
        text = inner["responseBody"]["application/json"]["body"]
    return json.loads(text)


def _print_summary(summary: Dict[str, Any]) -> None:
    print("=" * 60)
    print("AWS Bedrock Agent Action-Group Adapter Demo")
    print("=" * 60)
    print()
    print("Wiring:")
    print("  Bedrock Agent --(action-group event)--> Lambda handler")
    print("  Lambda handler --(normalized name/args)--> GovernanceToolset")
    print("  GovernanceToolset --PAG/ATM/PAA--> PaymentBackend")
    print("  Result --> serialized into Bedrock response envelope")
    print()
    for entry in summary["responses"]:
        body = _decode_body(entry["response"])
        verdict = "BLOCKED" if isinstance(body, dict) and body.get(
            "error"
        ) == "blocked_by_governance" else "OK"
        print(f"Scenario: {entry['label']}")
        print(f"  → {verdict}  body={body}")
        if verdict == "BLOCKED":
            print(
                f"     constraint={body['constraint_id']} point={body['point']}"
            )
    print()
    print("=" * 60)
    print("Trace persisted via session memory (keyed by sessionId)")
    print("=" * 60)
    print(f"Total governance events recorded: {len(summary['trace'])}")
    if summary["discrepancies"]:
        print(f"Audit discrepancies: {len(summary['discrepancies'])}")
        for d in summary["discrepancies"]:
            print(
                f"  [{d['type']}] action={d['action_id']} "
                f"constraint={d['constraint']}: {d['message']}"
            )
        print()
        print("Note: coverage discrepancies on hard-blocked actions are expected —")
        print("PAA never runs when PAG raises.")
    else:
        print("No audit discrepancies — trace is SARC-conformant.")
    print(f"\nInner backend invocations: {len(summary['inner_calls'])}")
    print("(The blocked $50,000 transfer never reached PaymentBackend.)")


async def main() -> None:
    summary = await run()
    _print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
