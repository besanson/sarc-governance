# LangGraph-style adapter

Wrap a LangGraph "tools node" with `GovernanceToolset` so that every tool
dispatch passes through SARC's PAG/ATM/PAA gates. No `langgraph` dependency
is required to run the demo — the types here mirror the real shapes.

## What the demo does

1. Defines `GraphState`, `ToolCall`, `ToolMessage` stand-ins for the
   LangGraph types.
2. Implements a `FunctionDispatchToolset` that satisfies `ToolsetProtocol`
   by routing to a `dict[str, async fn]`.
3. Wraps it with `GovernanceToolset` and a one-constraint spec that blocks
   outbound email to addresses outside `example.com`.
4. Builds a node function `tools_node(state) -> state` that drains
   `state.pending` and writes a `ToolMessage` for each — including
   blocked-by-governance messages so the agent loop can react.
5. Drives the node with three tool calls: a docs search (allowed), an
   internal email (allowed), and an external email (blocked).

## Run

```bash
python examples/langgraph_style_adapter/run_demo.py
```

Expected last lines:

```
  [OK]      tool=search_docs ...
  [OK]      tool=send_email  ... alice@example.com
  [BLOCKED] tool=send_email  ... constraint=ch_external_email at PAG

messages produced: 3  blocked: 1
```

## Plugging into a real LangGraph build

```python
from langgraph.graph import StateGraph
from langchain_core.messages import ToolMessage

from sarc_governance import GovernanceToolset, ConstraintViolation
from sarc_governance.specs import load_spec

governed = GovernanceToolset(wrapped=FunctionDispatchToolset(my_tools), spec=load_spec("spec.yaml"))

async def tools_node(state):
    for call in state["pending_tool_calls"]:
        try:
            result = await governed.call_tool(call["name"], call["args"])
            state["messages"].append(ToolMessage(tool_call_id=call["id"], content=result))
        except ConstraintViolation as exc:
            state["messages"].append(ToolMessage(
                tool_call_id=call["id"],
                content={"error": "blocked_by_governance",
                         "constraint_id": exc.constraint_id, "point": exc.point.value},
                status="error",
            ))
    return state

graph = StateGraph(MyState).add_node("tools", tools_node) ...
```

The blocked-message convention is what lets the agent observe and adapt:
on a `status="error"` ToolMessage with `error == "blocked_by_governance"`,
have the planning node either route the work to a human or stop.

## Persisting traces

If you have a session-memory store on `state` (or on a parent context),
pass `memory_getter` and `session_id_getter` to `GovernanceToolset`. The
auto-detection of `ctx.deps.memory` / `ctx.deps.session_id` does not
apply here because LangGraph's state shape is different.
