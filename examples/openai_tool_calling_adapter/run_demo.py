#!/usr/bin/env python3
"""OpenAI-style tool/function calling adapter for SARC.

OpenAI's chat-completions API returns tool calls as a list under the
assistant message:

    {"role": "assistant", "tool_calls": [
        {"id": "call_abc", "type": "function",
         "function": {"name": "...", "arguments": "...json..."}}
    ]}

Apps then dispatch each tool call locally and append a ``role: "tool"``
message with the result before the next model turn.

This example shows how to wrap that local dispatch with SARC governance.
No ``openai`` SDK is involved — the model output is constructed by hand.

Run::

    python examples/openai_tool_calling_adapter/run_demo.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    GovernanceToolset,
)


# ---------------------------------------------------------------------------
# Local function implementations.
# ---------------------------------------------------------------------------


async def get_weather(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"city": args["city"], "temp_c": 18, "conditions": "cloudy"}


async def transfer_funds(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "from": args["from"],
        "to": args["to"],
        "amount": args["amount"],
        "status": "executed",
    }


FUNCTIONS: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "get_weather": get_weather,
    "transfer_funds": transfer_funds,
}


# ---------------------------------------------------------------------------
# Adapter — exposes ToolsetProtocol over the function dict.
# ---------------------------------------------------------------------------


class OpenAIFunctionToolset:
    """Routes a SARC ``call_tool`` to a registered Python function."""

    def __init__(
        self,
        functions: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]],
    ) -> None:
        self._functions = functions
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        self.calls.append({"name": name, "args": dict(tool_args)})
        if name not in self._functions:
            raise KeyError(f"function not registered: {name!r}")
        return await self._functions[name](tool_args)


# ---------------------------------------------------------------------------
# OpenAI tool_call -> tool message dispatcher with SARC governance.
# ---------------------------------------------------------------------------


async def dispatch_tool_calls(
    governed: GovernanceToolset,
    tool_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Apply SARC PAG/ATM/PAA around each tool call.

    Returns the list of OpenAI-shaped ``role: "tool"`` messages to append to
    the conversation. Blocked calls produce a tool message with an error
    payload so the model can observe and adapt on its next turn.
    """
    out: List[Dict[str, Any]] = []
    for call in tool_calls:
        function = call["function"]
        name = function["name"]
        try:
            args = json.loads(function["arguments"])
        except json.JSONDecodeError:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps({"error": "invalid_arguments_json"}),
                }
            )
            continue

        try:
            result = await governed.call_tool(name, args)
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps(result),
                }
            )
        except ConstraintViolation as exc:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps(
                        {
                            "error": "blocked_by_governance",
                            "constraint_id": exc.constraint_id,
                            "point": exc.point.value,
                        }
                    ),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Spec — block large funds transfers; otherwise pass.
# ---------------------------------------------------------------------------


def _is_large_transfer(ctx: Dict[str, Any]) -> bool:
    return ctx["tool"] == "transfer_funds" and ctx["args"].get("amount", 0) >= 10_000


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
    ]
)


# ---------------------------------------------------------------------------
# Driver — synthesize the assistant message that would come from OpenAI.
# ---------------------------------------------------------------------------


def _assistant_tool_calls() -> List[Dict[str, Any]]:
    return [
        {
            "id": "call_001",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": json.dumps({"city": "Paris"}),
            },
        },
        {
            "id": "call_002",
            "type": "function",
            "function": {
                "name": "transfer_funds",
                "arguments": json.dumps({"from": "acct-A", "to": "acct-B", "amount": 250}),
            },
        },
        {
            "id": "call_003",
            "type": "function",
            "function": {
                "name": "transfer_funds",
                "arguments": json.dumps({"from": "acct-A", "to": "acct-C", "amount": 50_000}),
            },
        },
    ]


async def run() -> List[Dict[str, Any]]:
    inner = OpenAIFunctionToolset(FUNCTIONS)
    governed = GovernanceToolset(wrapped=inner, spec=SPEC)
    return await dispatch_tool_calls(governed, _assistant_tool_calls())


def _print(messages: List[Dict[str, Any]]) -> None:
    print("=" * 60)
    print("OpenAI Tool-Calling Adapter Demo")
    print("=" * 60)
    for m in messages:
        body = json.loads(m["content"])
        verdict = (
            "BLOCKED" if "error" in body and body["error"] == "blocked_by_governance" else "OK"
        )
        print(f"  [{verdict:7}] tool_call_id={m['tool_call_id']} name={m['name']}")
        print(f"           content={body}")


async def main() -> None:
    messages = await run()
    _print(messages)


if __name__ == "__main__":
    asyncio.run(main())
