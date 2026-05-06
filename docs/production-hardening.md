# Production hardening

`sarc-governance` is a developer toolkit moving toward a pre-production
foundation. Before you put it on a production critical path, the items
below need explicit decisions and engineering work. None is a SARC
research question — they are operational concerns common to any
policy-enforcement layer.

For a quick "what now ships" map, see
[`pre-production-checklist.md`](pre-production-checklist.md).

## Persistence

| Concern | What's there | What's needed |
|---|---|---|
| Constraint specs | YAML/JSON file loaded at process start; `PolicyMetadata` + `policy_checksum` for content fingerprinting; `policy diff` CLI for review-time deltas. | A versioned spec store with audit trail (git, signed objects in S3, or a policy DB). The library does not sign specs. |
| Trace records | `MemoryProtocol` interface plus in-process / JSONL / SQLite stores under `sarc_governance.stores`. | Multi-writer durable backend (relational DB, queue, OTel collector). Retention policy. The shipped stores are single-writer. |
| Action attribution | `ExecutionContext` dataclass auto-stamped onto trace records when supplied (principal / agent / tenant / session / roles / environment / request id). | Wiring from your auth layer to populate it; agreement on canonical role names. |

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

The library now ships a SHA-256 hash chain over canonical-JSON trace
records ([hashchain.py](../src/sarc_governance/hashchain.py)). All three
trace stores support `hash_chain=True` and `verify_chain` detects
record tampering, removal, or reordering. The CLI exposes
`sarc-governance trace verify-chain TRACE_FILE`.

This is **tamper-evident, not tamper-proof**. An attacker with write
access to the storage can recompute the chain after editing. To get
tamper-proofness you still need:

- Write-once / append-only storage (object lock on S3, WORM tape).
- Periodic anchoring of the chain head to an external timestamping
  authority if regulators ask.
- A signed receipt for the chain head at deployment time.

See [`security-model.md`](security-model.md) for the threat model.

## Policy authoring and approval

`sarc-governance validate` checks structure, not intent.
`sarc-governance policy inspect` prints a structured summary plus a
content-checksum, and `sarc-governance policy diff OLD NEW --exit-code`
gates pull requests on intentional changes. `PolicyMetadata` carries
descriptive lifecycle fields (`policy_id`, `version`, `approved_by`,
`approval_status`).

Still your responsibility:

- Spec PRs with mandatory reviewers (compliance, security).
- Static analysis of predicate complexity / blast radius (the library
  does not estimate "how many calls will this fire on?").
- Staged rollout: shadow → enforce-soft → enforce-hard, with a
  kill-switch.
- Reproducibility: stamp the `policy_id` + `version` + `checksum` onto
  every trace record via `ExecutionContext.metadata` or a wrapper around
  `MemoryProtocol`.

The library treats `approval_status` as informational. Whatever
"approved" means in your organisation, your CI/CD enforces it.

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
- run: sarc-governance validate config/spec.yaml
- run: sarc-governance policy inspect config/spec.yaml --json
- run: sarc-governance policy diff base:config/spec.yaml HEAD:config/spec.yaml --exit-code
- run: pytest
- run: python scripts/run_smoke.py --dump trace.jsonl
- run: sarc-governance trace verify-chain trace.jsonl
- run: sarc-governance audit config/spec.yaml trace.jsonl
```

Beyond that: signed releases, dependency review, image attestation if
you ship the agent as a container.

## What this list is *not*

This is not a roadmap for `sarc-governance`. The library is intentionally
small. The items above are things every adopting team will need to
decide and implement in their own infrastructure. The library exposes
clean seams (`MemoryProtocol`, `EscalationHandler`, `memory_getter`,
custom predicates) so those decisions stay outside the core.
