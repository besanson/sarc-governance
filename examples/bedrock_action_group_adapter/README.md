# AWS Bedrock Agent action-group adapter

Wrap an AWS Bedrock Agent action-group Lambda handler with
`GovernanceToolset` so every tool dispatch passes through SARC's
PAG/ATM/PAA gates before the Lambda talks to its downstream system. No
`boto3` or AWS SDK is required to run the demo — events and responses are
built by hand, and the "Lambda" is a plain Python function.

> **Honest scope.** This is a Lambda / action-group *adapter pattern*, not
> a certified Bedrock production integration. The goal is to show how the
> same SARC surface that wraps LangGraph, OpenAI tool calling, or any
> other async toolset wraps Bedrock's action-group boundary — using only
> `(name, args)` and an async `call_tool`.

## Does Bedrock call SARC?

**No.** Bedrock has its own action-group / runtime orchestration and does
not depend on SARC. SARC Governance wraps the tool-dispatch boundary the same
way it wraps any other async toolset: you put the `GovernanceToolset`
between the framework event and the downstream system.

In AWS terms, SARC lives **inside the Lambda** that backs the action
group, before it calls into the actual payments / CRM / ERP / etc.
service.

## What the demo does

1. Defines a mock downstream system (`PaymentBackend`) with
   `lookup_balance` and `transfer_funds` tools.
2. Declares a `ConstraintSpec` with:
   - a **hard / PAG** constraint that blocks transfers ≥ $10,000, and
   - a **soft / PAA** constraint that logs transfers ≥ $1,000 for review.
3. Implements `normalize_event(event)` — translating Bedrock's
   `actionGroup` / `function` (or `apiPath`) / `parameters` /
   `requestBody` / `sessionAttributes` into a SARC `(name, args)` call
   plus a lightweight `BedrockCallContext`.
4. Implements `build_response(...)` — serializing the SARC result into
   Bedrock's function-schema response envelope (or the apiSchema variant).
5. Wires the two in a `BedrockActionGroupHandler` that stands in for the
   Lambda entry point.
6. Runs four scenarios:
   - safe `lookup_balance` via a **function-schema** event,
   - a $2,500 transfer that fires the **soft PAA** constraint,
   - a $50,000 transfer that is **blocked at PAG** (never reaches the
     backend),
   - safe balance lookup via an **apiSchema** event (`apiPath` +
     `httpMethod` + `requestBody`).

Trace records are persisted via a session-memory store keyed by Bedrock's
`sessionId`, and `audit_trace` is run against the recorded trace at the
end.

## Run

```bash
python examples/bedrock_action_group_adapter/run_demo.py
```

Expected tail of output:

```
Scenario: safe lookup (function-schema)
  → OK  body={'account': 'acct-A', 'balance': 12500}
Scenario: mid transfer — soft PAA flag
  → OK  body={'from': 'acct-A', 'to': 'acct-B', 'amount': 2500, 'status': 'executed', ...}
Scenario: large transfer — hard PAG block
  → BLOCKED  body={'error': 'blocked_by_governance', ...}
     constraint=ch_large_transfer point=PAG
Scenario: safe lookup (api-schema)
  → OK  body={'account': 'acct-A', 'balance': 12500}
```

The blocked transfer never reaches `PaymentBackend`; `inner.calls` will
have three entries, not four.

## Event and response shapes

**Function-schema event (inbound to Lambda):**

```json
{
  "messageVersion": "1.0",
  "actionGroup": "PaymentActions",
  "function": "transfer_funds",
  "parameters": [
    {"name": "from", "type": "string", "value": "acct-A"},
    {"name": "to",   "type": "string", "value": "acct-B"},
    {"name": "amount", "type": "number", "value": "2500"}
  ],
  "sessionId": "session-001",
  "sessionAttributes": {"actor": "agent-0"},
  "promptSessionAttributes": {},
  "inputText": "..."
}
```

**Function-schema response (outbound from Lambda):**

```json
{
  "messageVersion": "1.0",
  "response": {
    "actionGroup": "PaymentActions",
    "function": "transfer_funds",
    "functionResponse": {
      "responseBody": {"TEXT": {"body": "<json-encoded result>"}}
    }
  },
  "sessionAttributes": {...},
  "promptSessionAttributes": {...}
}
```

**OpenAPI-schema action groups** arrive with `apiPath` / `httpMethod` /
`requestBody` instead of `function` / `parameters`; the adapter normalizes
both into `(name, args)` and emits the corresponding response shape. In
the demo we synthesize the tool name as `"<METHOD> <path>"` so the
`ConstraintSpec` can target API-schema calls the same way.

## Plugging into a real AWS Lambda

```python
# lambda_function.py
import asyncio

from sarc_governance import GovernanceToolset, EscalationRouter
from sarc_governance.specs import load_spec

from .bedrock_adapter import (  # your adapter module
    BedrockActionGroupHandler,
    PaymentBackend,
)

SPEC = load_spec("sarc_spec.yaml")
_HANDLER = BedrockActionGroupHandler(
    governed=GovernanceToolset(wrapped=PaymentBackend(), spec=SPEC),
    memory=YourDurableSessionMemory(),  # DDB / Redis / ... — satisfies MemoryProtocol
)


def lambda_handler(event, context):
    return asyncio.run(_HANDLER.handle(event))
```

The SARC layer is **invisible to Bedrock**. The agent loop only ever sees
action-group calls and action-group responses; PAG blocks surface as
normal action-group errors (a `403` for API-schema, or a structured error
body in the function-schema TEXT body) so the agent can observe and
adapt.

## Notes

- No boto3, no AWS calls. Replace `PaymentBackend` with anything that
  satisfies `ToolsetProtocol` (a class with `async def call_tool(name,
  args, ctx, tool)`).
- Trace persistence uses an in-process dict; swap in a durable
  `MemoryProtocol` implementation (DynamoDB, Redis, etc.) for real
  deployments.
- The adapter passes the full `BedrockCallContext` as the SARC `ctx`
  argument, so predicates can read `sessionAttributes`, the invoking
  `agent`, or the action-group name if they need to.
- The default `EscalationRouter` logs only — in real AWS, wire it to SNS,
  SQS, EventBridge, or your paging system.
