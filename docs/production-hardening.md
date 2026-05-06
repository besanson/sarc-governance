# Production hardening

`sarc-kaos` is a developer toolkit and reference implementation. Before
you put it on a production critical path, the following gaps need
explicit decisions and engineering work. None of these is a SARC research
question — they are operational concerns common to any policy-enforcement
layer.

## Persistence

| Concern | What's there | What's needed |
|---|---|---|
| Constraint specs | YAML/JSON file loaded at process start. | A versioned spec store with audit trail (git, signed objects in S3, or a policy DB). |
| Trace records | `MemoryProtocol` interface; only an in-process implementation ships. | Durable backend (relational DB, append-only log, OTel collector). Retention policy. |
| Action attribution | Captured by callers; not normalized. | Schema for actor/session/agent identity flowing into every record. |

Provide your own `MemoryProtocol` implementation and pass it via the
`memory_getter` callback (or via `ctx.deps.memory` if your context object
already exposes that shape). The library does not make a storage choice
for you.

## Observability

| Concern | What's there | What's needed |
|---|---|---|
| Metrics | None. | Counters per constraint × point × outcome (`fired_total`, `blocked_total`, `routed_total`). Histogram of `TraceRecord.extra["elapsed"]`. |
| Tracing | None. | OpenTelemetry spans on the wrapped `call_tool` with attributes for constraint outcomes. |
| Structured logs | The default escalation handler emits one `WARNING`. | JSON-structured logs with action_id correlation; a sink that doesn't drop on backpressure. |

The `EscalationRouter` and `GovernanceToolset` both expose the events
needed; emitting them is your job.

## Authentication and authorization

The library has no concept of *who* is calling. Real deployments need:

- An identity bound to the agent invocation (service account, user
  delegation, on-behalf-of token).
- A policy that maps identity to constraint-set selection (e.g. junior
  agents get a stricter spec).
- Scoped access for the escalation reviewer interface.
- Rate limits on tool invocations and on escalation routing — neither is
  implemented.

## Tamper-evident audit logs

`TraceRecord`s today are plain dicts. Production-grade audit needs:

- Cryptographic chaining (hash-linked entries) or write-once storage.
- A canonical serialization so the same event always hashes the same way.
- Periodic anchoring to an external timestamping authority if regulators
  ask.

## Policy authoring and approval

`sarc-kaos validate` checks structure, not intent. A real lifecycle adds:

- Spec PRs with mandatory reviewers (compliance, security).
- Static analysis: predicate complexity, blast radius if a constraint
  starts firing on more actions than expected.
- Staged rollout: shadow → enforce-soft → enforce-hard, with a kill-switch.
- Reproducibility: the spec version-id is recorded on every `TraceRecord`.

## Runtime sandboxing

`Constraint.predicate` is arbitrary Python evaluated in-process. Treat
spec content as code, not configuration:

- Specs from untrusted sources should not be loaded at all, or should be
  restricted to a registry of pre-approved predicates by name.
- For richer logic, consider compiling to OPA/Rego or CEL at the
  enforcement layer instead of executing Python predicates directly.

## Concurrency and ordering

A single `GovernanceToolset` keeps a monotonic action counter under no
lock. For parallel actors:

- Either give each actor its own `GovernanceToolset` instance (cheapest),
- or replace `_next_action_id` with a UUID/ULID generator and add a lock
  around any mutable shared state your handlers introduce.

`asyncio.gather` over the same instance from multiple agent loops is not
supported.

## Reviewer / escalation infrastructure

The `EscalationRouter` only routes. For production human-in-the-loop:

- A queue (work item / ticket) the reviewer actually lives in.
- Authorization that the reviewer is allowed to approve this class.
- A timeout policy (how long does "no answer" become "deny"?).
- An audit trail linking the reviewer's decision back to the action.
- A re-entry path so the action can resume on approval.

The pattern in [`examples/human_escalation/`](../examples/human_escalation/README.md)
shows the SARC-side wiring; the queue/UI/auth side is where the real
engineering goes.

## Performance

The reference benchmark in [`benchmarks/`](../benchmarks/README.md) measures
governance overhead with synthetic workloads. Before production, run:

- Throughput on representative tool mix and predicate cost.
- Tail latency under load (especially p99 with PAA constraints).
- Failure injection: handler exceptions, memory backend stalls.

## CI/CD

A minimum gate set:

```yaml
- run: sarc-kaos validate config/spec.yaml
- run: pytest
- run: python scripts/run_smoke.py --dump trace.json
- run: sarc-kaos audit config/spec.yaml trace.json
```

Beyond that: signed releases, dependency review, image attestation if
you ship the agent as a container.

## What this list is *not*

This is not a roadmap for `sarc-kaos`. The library is intentionally
small. The items above are things every adopting team will need to
decide and implement in their own infrastructure. The library exposes
clean seams (`MemoryProtocol`, `EscalationHandler`, `memory_getter`,
custom predicates) so those decisions stay outside the core.
