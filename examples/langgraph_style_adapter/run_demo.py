#!/usr/bin/env python3
"""LangGraph-style adapter for SARC.

LangGraph models a workflow as a graph of nodes; tool execution typically
happens inside a "tools" node that consumes a pending ``ToolCall`` from the
state and produces a ``ToolMessage``. This example shows how to slot SARC's
``GovernanceToolset`` into that node *without* importing LangGraph.

The shapes mirror the public LangGraph types just enough to make the wiring
obvious. If you have LangGraph installed, replacing ``ToolCall`` /
``ToolMessage`` / ``GraphState`` with the real classes is mechanical.

Run::

    python examples/langgraph_style_adapter/run_demo.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sarc_kaos import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    GovernanceToolset,
)


# ---------------------------------------------------------------------------
# LangGraph-shaped types (stand-ins; no langgraph dependency).
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any]
    id: str


@dataclass
class ToolMessage:
    tool_call_id: str
    name: str
    content: Any
    status: str = "ok"  # "ok" | "blocked" | "error"


@dataclass
class GraphState:
    messages: List[ToolMessage] = field(default_factory=list)
    pending: List[ToolCall] = field(default_factory=list)
    blocked: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Example "tool functions". A LangGraph project would have these as @tool
# decorated callables; here they're plain async functions.
# ---------------------------------------------------------------------------


async def _search_docs(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"query": args["query"], "hits": [{"id": "doc-1", "score": 0.9}]}


async def _send_email(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"to": args["to"], "subject": args["subject"], "sent": True}


TOOLS: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "search_docs": _search_docs,
    "send_email": _send_email,
}


# ---------------------------------------------------------------------------
# Adapter — exposes ToolsetProtocol over a flat function dict.
# ---------------------------------------------------------------------------


class FunctionDispatchToolset:
    """Implements ``ToolsetProtocol`` by routing to a dict of async functions."""

    def __init__(
        self, tools: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]]
    ) -> None:
        self._tools = tools
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        self.calls.append({"tool": name, "args": dict(tool_args)})
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return await self._tools[name](tool_args)


# ---------------------------------------------------------------------------
# The "tools node" — the function a LangGraph build would register.
# ---------------------------------------------------------------------------


def make_tools_node(governed: GovernanceToolset) -> Callable[[GraphState], Awaitable[GraphState]]:
    """Return an async node function that dispatches all pending tool calls."""

    async def tools_node(state: GraphState) -> GraphState:
        for call in state.pending:
            try:
                result = await governed.call_tool(call.name, call.args)
                state.messages.append(
                    ToolMessage(
                        tool_call_id=call.id,
                        name=call.name,
                        content=result,
                        status="ok",
                    )
                )
            except ConstraintViolation as exc:
                # Surface the block in the message stream so downstream
                # nodes (planner / agent loop) can react to it.
                state.messages.append(
                    ToolMessage(
                        tool_call_id=call.id,
                        name=call.name,
                        content={
                            "error": "blocked_by_governance",
                            "constraint_id": exc.constraint_id,
                            "point": exc.point.value,
                        },
                        status="blocked",
                    )
                )
                state.blocked.append(
                    {
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "constraint_id": exc.constraint_id,
                        "point": exc.point.value,
                    }
                )
        state.pending = []
        return state

    return tools_node


# ---------------------------------------------------------------------------
# Spec — block emails to non-corporate addresses; otherwise pass.
# ---------------------------------------------------------------------------


def _is_external_email(ctx: Dict[str, Any]) -> bool:
    if ctx["tool"] != "send_email":
        return False
    to = ctx["args"].get("to", "")
    return not to.endswith("@example.com")


SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="ch_external_email",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_is_external_email,
            description="Block outbound email to addresses outside example.com.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def run() -> GraphState:
    inner = FunctionDispatchToolset(TOOLS)
    governed = GovernanceToolset(wrapped=inner, spec=SPEC)
    tools_node = make_tools_node(governed)

    state = GraphState(
        pending=[
            ToolCall(name="search_docs", args={"query": "sarc paper"}, id="tc-1"),
            ToolCall(
                name="send_email",
                args={"to": "alice@example.com", "subject": "results"},
                id="tc-2",
            ),
            ToolCall(
                name="send_email",
                args={"to": "ceo@external.com", "subject": "leak"},
                id="tc-3",
            ),
        ]
    )
    return await tools_node(state)


def _print(state: GraphState) -> None:
    print("=" * 60)
    print("LangGraph-style Adapter Demo")
    print("=" * 60)
    for m in state.messages:
        if m.status == "blocked":
            print(
                f"  [BLOCKED] tool={m.name} call_id={m.tool_call_id} "
                f"constraint={m.content['constraint_id']} at {m.content['point']}"
            )
        else:
            print(f"  [OK]      tool={m.name} call_id={m.tool_call_id} content={m.content}")
    print()
    print(f"messages produced: {len(state.messages)}  blocked: {len(state.blocked)}")


async def main() -> None:
    state = await run()
    _print(state)


if __name__ == "__main__":
    asyncio.run(main())
