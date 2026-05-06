# OpenAI tool-calling adapter

Wrap an OpenAI-style function/tool-calling dispatch with `GovernanceToolset`
so every locally invoked function passes through SARC's PAG/ATM/PAA gates.
No `openai` SDK is involved — the assistant's `tool_calls` payload is
constructed by hand.

## What the demo does

1. Implements two example functions (`get_weather`, `transfer_funds`).
2. Adapts them with `OpenAIFunctionToolset`, which satisfies
   `ToolsetProtocol`.
3. Wraps that with `GovernanceToolset` and a one-constraint spec that
   blocks transfers ≥ $10,000.
4. Synthesizes a faux assistant message with three tool calls and runs
   `dispatch_tool_calls` to produce the resulting `role: "tool"` messages.

Blocked calls produce a `role: "tool"` message with an error payload
(`{"error": "blocked_by_governance", "constraint_id": ..., "point": ...}`)
so the model can observe and adapt on its next turn.

## Run

```bash
python examples/openai_tool_calling_adapter/run_demo.py
```

Expected output (last block):

```
  [OK     ] tool_call_id=call_001 name=get_weather
  [OK     ] tool_call_id=call_002 name=transfer_funds (amount 250)
  [BLOCKED] tool_call_id=call_003 name=transfer_funds (amount 50000)
           content={'error': 'blocked_by_governance', 'constraint_id': 'ch_large_transfer', 'point': 'PAG'}
```

## Plugging into a real OpenAI app

```python
from openai import AsyncOpenAI
from sarc_kaos import GovernanceToolset
from sarc_kaos.specs import load_spec

client = AsyncOpenAI()
governed = GovernanceToolset(
    wrapped=OpenAIFunctionToolset(my_functions),
    spec=load_spec("spec.yaml"),
)

response = await client.chat.completions.create(model=..., messages=..., tools=[...])
choice = response.choices[0].message
if choice.tool_calls:
    tool_messages = await dispatch_tool_calls(
        governed,
        [tc.model_dump() for tc in choice.tool_calls],
    )
    messages.extend(tool_messages)
```

The dispatcher returns the exact list of `{"role": "tool", ...}` messages
to append to the conversation before the next `chat.completions.create`
call. SARC's enforcement is invisible to the model on the success path and
shows up as a normal tool error on blocks.
