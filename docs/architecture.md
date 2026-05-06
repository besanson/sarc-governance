# Architecture

`sarc-kaos` implements the SARC runtime governance architecture from the
SARC paper. It is a thin, framework-neutral library that interposes on
every tool dispatch and enforces declarative constraints at three points
around the call.

## The SARC loop

```
                      +-------------------------------+
   tool request ----> |       GovernanceToolset       |  <----- ConstraintSpec
                      |                               |
                      |    PAG (Pre-Action Gate)      |  hard / escalation
                      |       v                       |
                      |    ATM (Action-Time Monitor)  |  hard / escalation
                      |       v                       |
                      |    inner toolset call         |
                      |       v                       |
                      |    PAA (Post-Action Auditor)  |  soft / escalation
                      +---------------+---------------+
                                      |
                                      v
                                 ER (router)
                                      |
                                      v
                                 trace memory
```

Three points, three classes, two orthogonal concerns: when to evaluate
(`EnforcementPoint`) and how strict (`ConstraintClass`).

## Class × point compatibility (paper §4.2, Table 1)

| Class | Allowed points | Why |
|---|---|---|
| `hard` | `PAG`, `ATM` | Must be able to prevent or interrupt execution. |
| `soft` | `ATM`, `PAA` | Observes the action; never blocks. |
| `escalation` | `PAG`, `PAA` | Routes events asynchronously, before or after. |

Constructing a `Constraint` with an incompatible pair raises `ValueError`
at definition time; a runtime trace that records an evaluation at an
incompatible point is flagged by `audit_trace` as a placement discrepancy.

## Components

| Component | Module | Role |
|---|---|---|
| `Constraint`, `ConstraintSpec` | `sarc_kaos.constraints` | Declarative governance unit; immutable, validated. |
| `GovernanceToolset` | `sarc_kaos.governance` | Wraps any `ToolsetProtocol`; enforces PAG/ATM/PAA. |
| `EscalationRouter` (ER) | `sarc_kaos.escalation` | Async dispatcher for fired escalation events. |
| `TraceRecord`, `ActionEvent` | `sarc_kaos.trace` | Per-evaluation audit record. |
| `audit_trace` | `sarc_kaos.audit` | Offline I1 (coverage) / I2 (placement) / I3 (response) checker. |
| Predicate registry | `sarc_kaos.predicates` | Named, code-by-reference predicates loaded from YAML. |
| Spec loader | `sarc_kaos.specs` | YAML/JSON → `ConstraintSpec`, no `eval`. |
| CLI | `sarc_kaos.cli` | `validate` / `list-predicates` / `audit` / `demo`. |

## Mapping to KAOS-shaped toolsets

KAOS (and pydantic-ai) expose tool dispatch through an `AbstractToolset`
whose `call_tool(name, tool_args, ctx, tool)` signature is exactly what
`GovernanceToolset` consumes and forwards. Two consequences:

1. **No adapter code is needed.** Pass an `AbstractToolset` to
   `GovernanceToolset(wrapped=...)` and the agent loop is unchanged.
2. **Trace persistence auto-detects** `ctx.deps.memory` and
   `ctx.deps.session_id`. If your project shape is different, supply
   `memory_getter=` and `session_id_getter=` callables instead.

Other framework shapes (LangGraph, OpenAI tool calling) need a small
adapter object that implements `ToolsetProtocol` over their native
dispatch. See [`integrations.md`](integrations.md) for the patterns.

## Trace record schema

Every evaluation produces one `TraceRecord` with these fields:

| Field | Type | Notes |
|---|---|---|
| `action_id` | str | Per-invocation identifier; shared across PAG/ATM/PAA records. |
| `tool` | str | The tool name. |
| `point` | str | `PAG` / `ATM` / `PAA`. |
| `constraint_id` | str | `Constraint.id`. |
| `class` | str | Denormalised; saves a spec lookup at audit time. |
| `fired` | bool | Predicate result. |
| `response` | str | Constraint's declared response. |
| `timestamp` | float | `time.time()`. |
| `extra` | dict | Optional. ATM records carry `{"elapsed": float}`. |

`audit_trace` also accepts the higher-level "action-level" schema used by
`benchmarks/sarc_eval.py`; it is auto-detected.

## What the library deliberately does *not* do

- Decide outcomes after escalation. The router routes; a paired `hard`
  constraint reading a ledger is the actual gate. See
  [`examples/human_escalation/`](../examples/human_escalation/README.md).
- Persist anything beyond the in-process `MemoryProtocol` you supply.
- Sandbox predicates. `Constraint.predicate` is arbitrary Python; treat
  spec content as code, not data.
- Provide retries, backoff, or idempotency around the inner toolset.
- Coordinate concurrent agents. A `GovernanceToolset` is single-actor.
