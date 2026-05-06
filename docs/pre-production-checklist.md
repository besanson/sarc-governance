# Pre-production checklist

This is the short list of things `sarc-governance` does *itself* now, and
the things you still have to wire to your own infrastructure before
putting an agent on a production critical path. It supersedes the
"Persistence / Observability / Tamper-evident" sections of
[`production-hardening.md`](production-hardening.md) for items the
library now ships.

## What `sarc-governance` provides today

- **Spec model + validation** — `Constraint`, `ConstraintSpec`, class ×
  point compatibility (paper §4.2, Table 1).
- **Runtime enforcement** — `GovernanceToolset` at PAG / ATM / PAA.
- **Execution context** — `ExecutionContext` dataclass for principal /
  agent / tenant / session / roles / environment / request id,
  auto-stamped onto trace records when supplied
  ([context.py](../src/sarc_governance/context.py)).
- **Policy lifecycle primitives** — `PolicyMetadata`, `inspect_policy`,
  `policy_checksum`, `diff_policies`. Metadata is *informational only* —
  the library does not validate signatures or enforce a workflow
  ([policy.py](../src/sarc_governance/policy.py)).
- **Durable trace stores** —
  [`MemoryTraceStore`](../src/sarc_governance/stores/memory.py),
  [`JSONLTraceStore`](../src/sarc_governance/stores/jsonl.py),
  [`SQLiteTraceStore`](../src/sarc_governance/stores/sqlite.py). All
  three implement an append / list / iter / export-jsonl protocol.
- **Tamper-evident hash chain** — SHA-256 chain over canonical JSON of
  each record. Stores can opt in (`hash_chain=True`) and `verify_chain`
  detects tampering, removal, or reordering
  ([hashchain.py](../src/sarc_governance/hashchain.py)). This is
  *tamper-evident*, not *tamper-proof* — see
  [`security-model.md`](security-model.md).
- **CLI** — `validate`, `list-predicates`, `audit`, `policy inspect`,
  `policy diff`, `trace verify-chain`, `trace export`, `demo`. All
  produce useful exit codes.
- **Failure-mode safety** — escalation handler exceptions and trace
  store / memory backend exceptions are caught and logged. A failing
  escalation handler does **not** turn a hard PAG block into a pass.
  See [`failure-modes.md`](failure-modes.md).

## CI gate

Minimum gate set (drop in to your pipeline):

```yaml
- run: sarc-governance validate config/spec.yaml
- run: sarc-governance policy inspect config/spec.yaml --json
- run: sarc-governance policy diff main:config/spec.yaml HEAD:config/spec.yaml --exit-code
- run: pytest
- run: python scripts/run_smoke.py --dump trace.jsonl
- run: sarc-governance trace verify-chain trace.jsonl
- run: sarc-governance audit config/spec.yaml trace.jsonl
```

(`policy diff --exit-code` will return non-zero on any change, which is
useful as a "force human review" gate; remove it if your workflow expects
auto-merge of constraint edits.)

## What you still have to provide

These are still your responsibility — the library exposes seams but does
not pick a vendor:

- **Identity / RBAC** — populate `ExecutionContext` from your auth
  layer. Predicates can then consult `ctx["execution_context"].roles` /
  `principal_id` etc.
- **Escalation infrastructure** — the default handler logs only.
  Replace it with a queue / ticket system / pager (see
  [`examples/human_escalation/`](../examples/human_escalation/README.md)
  for the SARC-side wiring pattern).
- **Storage** — pick `JSONLTraceStore` or `SQLiteTraceStore` for
  single-process work; bring your own `MemoryProtocol` for a relational
  DB or queue. Define a retention policy.
- **Metrics / tracing** — emit counters per constraint × point ×
  outcome. The library does not depend on OpenTelemetry; an
  OTel adapter is straightforward to write against the trace store
  protocol.
- **Spec approval workflow** — `PolicyMetadata.approval_status` is a
  string. Your CI/CD enforces what `approved` means.
- **Predicate sandboxing** — predicates are arbitrary Python evaluated
  in-process. Treat specs from untrusted sources as code, not data.
- **Concurrency** — the library is single-actor friendly. Use one
  `GovernanceToolset` instance per concurrent agent loop.

## Status mapping

| Concern | Pre-this-release | Now ships in library |
|---|---|---|
| Trace persistence | `MemoryProtocol` only | + JSONL + SQLite |
| Tamper-evident audit | None | Hash chain + verify CLI |
| Spec versioning | None | `PolicyMetadata` + checksum + diff |
| Identity in trace | Ad-hoc | `ExecutionContext` dataclass + auto-stamp |
| Escalation safety | Suppressed | Documented + tested |
| CI policy review | `validate` only | + `policy inspect` + `policy diff --exit-code` |
| Trace verify in CI | None | `trace verify-chain` |

Items still left to the deploying organisation are listed in
[`production-hardening.md`](production-hardening.md).
