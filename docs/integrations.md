# Integration patterns

`GovernanceToolset` wraps any object whose `call_tool(name, args, ctx, tool)`
method is async. That makes integration with most agent frameworks a small
adapter problem, not a fork. Below are five worked patterns.

## The common shape

Every integration follows the same four-step recipe — only the surface details change:

```
framework tool-call event   ──►   normalize to (name, args)           [adapter]
                                  ▼
                           GovernanceToolset.call_tool(name, args, ctx)
                                  ▼ PAG / ATM / inner call / PAA
                           result   or   ConstraintViolation
                                  ▼
                           serialize back to the framework's response shape  [adapter]
```

| Framework | Tool-call event shape | Response shape | Adapter needed |
|---|---|---|---|
| **KAOS / pydantic-ai** | `AbstractToolset.call_tool(name, tool_args, ctx, tool)` | return value of `call_tool` | **None** — same shape |
| **LangGraph** | `ToolCall(name, args, id)` on graph state | `ToolMessage(tool_call_id, content, status)` | small `tools_node` |
| **OpenAI tool calling** | `assistant.tool_calls[].function.{name, arguments}` | `{"role": "tool", "tool_call_id", "content"}` | `dispatch_tool_calls` |
| **AWS Bedrock action group** | Lambda event with `actionGroup` + `function`/`apiPath` + `parameters`/`requestBody` + `sessionAttributes` | `{"messageVersion", "response": {functionResponse \| responseBody}, "sessionAttributes", ...}` | Lambda handler with `normalize_event` + `build_response` |
| **Generic async toolset** | whatever you have | whatever you have | one class with `async def call_tool` |

None of these frameworks call SARC, and SARC does not import any of them. The
adapter is just data marshaling around a single async method.

## 1. KAOS / pydantic-ai (zero-adapter)

KAOS' `AbstractToolset` already has the right shape. Wrap it directly:

```python
from sarc_kaos import GovernanceToolset
from sarc_kaos.specs import load_spec

spec = load_spec("config/sarc_spec.yaml")
governed = GovernanceToolset(wrapped=my_kaos_toolset, spec=spec)
# Hand `governed` to the agent wherever `my_kaos_toolset` would have gone.
```

The library auto-detects `ctx.deps.memory` and `ctx.deps.session_id` for
trace persistence — no extra wiring is needed inside a typical KAOS app.

A runnable, dependency-free version using mock `RunContext` /
`AgentDeps` lives at
[`examples/kaos_style_adapter/`](../examples/kaos_style_adapter/README.md).

> **`sarc-kaos` does not import KAOS or pydantic-ai.** Both are optional.
> The package depends only on `pyyaml` plus the standard library.

## 2. LangGraph-style "tools node"

LangGraph models a workflow as a graph; tool calls run inside a node that
consumes pending `ToolCall`s and emits `ToolMessage`s. Adapt the function
dict to `ToolsetProtocol` and call it from the node:

```python
class FunctionDispatchToolset:
    def __init__(self, fns): self._fns = fns
    async def call_tool(self, name, args, ctx, tool):
        return await self._fns[name](args)

governed = GovernanceToolset(wrapped=FunctionDispatchToolset(my_fns), spec=spec)

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
```

Worked dependency-free demo:
[`examples/langgraph_style_adapter/`](../examples/langgraph_style_adapter/README.md).

## 3. OpenAI tool calling

OpenAI returns tool calls under `assistant.tool_calls`; the app dispatches
them locally and appends `role: "tool"` messages. Wrap the local dispatch:

```python
class OpenAIFunctionToolset:
    def __init__(self, fns): self._fns = fns
    async def call_tool(self, name, args, ctx, tool):
        return await self._fns[name](args)

governed = GovernanceToolset(wrapped=OpenAIFunctionToolset(my_fns), spec=spec)

async def dispatch_tool_calls(governed, tool_calls):
    out = []
    for call in tool_calls:
        args = json.loads(call["function"]["arguments"])
        try:
            result = await governed.call_tool(call["function"]["name"], args)
            out.append({"role": "tool", "tool_call_id": call["id"],
                        "name": call["function"]["name"],
                        "content": json.dumps(result)})
        except ConstraintViolation as exc:
            out.append({"role": "tool", "tool_call_id": call["id"],
                        "name": call["function"]["name"],
                        "content": json.dumps({"error": "blocked_by_governance",
                                                "constraint_id": exc.constraint_id,
                                                "point": exc.point.value})})
    return out
```

Worked dependency-free demo:
[`examples/openai_tool_calling_adapter/`](../examples/openai_tool_calling_adapter/README.md).

## 4. AWS Bedrock Agent action groups

AWS Bedrock Agents dispatch tool calls to a Lambda action-group handler.
The Lambda receives a JSON event with `actionGroup`, `function` (or `apiPath`
for OpenAPI-schema action groups), `parameters` (or `requestBody`), and
`sessionId` / `sessionAttributes`, and must return a specific response
envelope. **Bedrock has its own action-group orchestration; it does not
call KAOS or SARC.** SARC sits *inside the Lambda*, between the Bedrock
event and the actual downstream system:

```python
from sarc_kaos import GovernanceToolset, ConstraintViolation

class BedrockActionGroupHandler:
    def __init__(self, governed: GovernanceToolset, memory):
        self.governed = governed
        self.memory = memory

    async def handle(self, event):
        norm = normalize_event(event)         # actionGroup + function/apiPath + params -> (name, args)
        ctx  = BedrockCallContext(            # whatever predicates need to read
            session_id=norm["session_id"],
            action_group=norm["action_group"],
            session_attributes=norm["session_attributes"],
            memory=self.memory,
        )
        try:
            result = await self.governed.call_tool(norm["name"], norm["args"], ctx=ctx)
            body, status = result, 200
        except ConstraintViolation as exc:
            body = {"error": "blocked_by_governance",
                    "constraint_id": exc.constraint_id, "point": exc.point.value}
            status = 403
        return build_response(                # back into Bedrock envelope
            action_group=norm["action_group"],
            function_or_path=norm["name"],
            body=body, http_status=status,
            session_attributes=ctx.session_attributes,
            prompt_session_attributes=ctx.prompt_session_attributes,
            is_api="apiPath" in event,
        )
```

The handler keeps SARC ignorant of Bedrock specifics — it only sees
`(name, args)` and a context object, the same as every other integration.
Trace persistence uses `memory_getter` / `session_id_getter` that read
from `BedrockCallContext` (Bedrock's session shape is not the KAOS
`ctx.deps.memory` shape).

> **Honest scope.** This is a Lambda / action-group adapter pattern, not
> a certified Bedrock production integration. Replace the in-process
> memory with a durable `MemoryProtocol` (DynamoDB, Redis, …) and wire the
> `EscalationRouter` to SNS / SQS / EventBridge / your paging system before
> running it in front of real money or real customers.

Worked dependency-free demo:
[`examples/bedrock_action_group_adapter/`](../examples/bedrock_action_group_adapter/README.md).

## 5. Generic async toolset

Any custom framework can be wrapped by writing a class with a single
async `call_tool` method:

```python
class MyToolset:
    async def call_tool(self, name, args, ctx, tool):
        # forward to whatever your framework exposes
        return await my_framework_dispatch(name, args)

governed = GovernanceToolset(wrapped=MyToolset(), spec=spec)
```

For trace persistence in a non-KAOS shape, supply
`memory_getter=lambda ctx: ...` and `session_id_getter=lambda ctx: ...`
to extract the memory and session id from your context object on every
call.

## Honest about what is *not* here

- `sarc-kaos` does **not** import or vendor KAOS. There is no
  `pydantic-ai` integration package — it works with pydantic-ai because
  the toolset shapes overlap, not because we ship glue code.
- Trace persistence is only as durable as the `MemoryProtocol`
  implementation you give it. The bundled demos use in-process dicts.
- The default `EscalationRouter` logs only. Real deployments need a
  ticketing/queue/paging integration; the example at
  [`examples/human_escalation/`](../examples/human_escalation/README.md)
  shows the *pattern* for human approval but not a ready-to-ship
  reviewer system.

## Choosing where to wire it in

Whatever framework you use, the cheapest place to wrap is the seam your
agent code already uses to dispatch tools. That keeps the agent loop
unchanged and means the only thing the SARC layer sees is the
`(name, args)` you would have passed anyway.
