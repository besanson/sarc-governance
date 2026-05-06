# KAOS-style Adapter Example

Shows that `GovernanceToolset` works against a KAOS / pydantic-ai-shaped
`RunContext` with **zero adapter code** — no KAOS install, no pydantic-ai install.

## What this demonstrates

KAOS exposes tool dispatch through an `AbstractToolset` whose method signature is

```python
async def call_tool(name, tool_args, ctx, tool) -> Any
```

and where `ctx` is a `RunContext[AgentDeps]` that carries dependencies on
`ctx.deps`, conventionally including a session memory and a session id.

`GovernanceToolset` is structurally compatible with that shape:

- Its `call_tool` signature is identical.
- It auto-detects `ctx.deps.memory` and `ctx.deps.session_id` at every call
  and persists each `TraceRecord` via `memory.add_event(...)`.

This demo defines a tiny stand-in `RunContext` / `AgentDeps` / `InProcessMemory`
and a mock customer-service toolset, then wraps the toolset and runs four
scenarios.

## Files

| File | Purpose |
|---|---|
| `run_demo.py` | Runnable demo with fake `ctx.deps.memory` / `ctx.deps.session_id` |

## Running

From the repo root, with the package installed:

```bash
python examples/kaos_style_adapter/run_demo.py
```

## Spec exercised

| ID | Class | Point | Trigger |
|---|---|---|---|
| `ch_refund_cap` | hard | PAG | refund amount ≥ $1,000 |
| `cs_refund_audit` | soft | PAA | refund result amount ≥ $500 |

## Scenarios

| # | Tool | Args | Expected outcome |
|---|---|---|---|
| 1 | `crm.lookup_account` | `account_id=A-100` | `OK` (no constraint applies) |
| 2 | `crm.issue_refund` | `amount=250` | `OK` |
| 3 | `crm.issue_refund` | `amount=750` | `OK`, soft PAA flag fires |
| 4 | `crm.issue_refund` | `amount=5000` | `BLOCKED [ch_refund_cap at PAG]` |

After all scenarios run, the demo prints how many trace records were persisted
on `ctx.deps.memory` and the result of `audit_trace` over them.

## Why this matters for KAOS users

To plug SARC into a real KAOS app, you do exactly what this demo does: keep
your existing toolset, wrap it with `GovernanceToolset(wrapped=…, spec=…)`,
and pass it to the agent wherever the toolset would otherwise go. The agent
loop and tool definitions don't change. Trace records will land on whatever
`AgentDeps.memory` you already have.
