# FAQ

Direct answers to questions a senior engineer is likely to ask before
adopting `sarc-governance`.

## Does this library call any cloud provider?

**No.** The runtime depends only on `pyyaml` plus the Python standard
library. It does not import boto3, the OpenAI SDK, LangGraph,
Anthropic SDK, or any other framework, and it does not make network
calls. The shipped Bedrock / LangGraph / OpenAI examples are
dependency-free reference adapters that mock the framework's event
shape — they do not call AWS, OpenAI, or LangGraph at runtime.

## Is `sarc-governance` a replacement for Bedrock / LangGraph / OpenAI tool calling?

**No.** Those are *orchestration* layers that decide which tool to
call. SARC is a *governance* layer that wraps the dispatch boundary
once the orchestration has decided. They live at different points in
the stack and compose: the orchestration produces a `(name, args)`
event, an adapter normalizes it into SARC's surface, SARC runs
PAG/ATM/PAA, then the inner toolset executes.

## Is `sarc-governance` production-ready?

**Not by itself.** The library deliberately stops short of decisions
that belong to the deploying organisation. The core enforcement loop
and the developer toolkit (CLI, audit, policy diff, hash chain) are
stable and tested (190 tests). What it *does not* ship — and what you
must provide before a critical path — is enumerated in
[`production-hardening.md`](production-hardening.md). Highlights:
multi-writer durable storage, an escalation queue / ticketing
system, RBAC wired into `ExecutionContext`, OpenTelemetry exporters,
and a real spec-approval workflow.

The README's status section calls this "developer toolkit + pre-production
foundations". That is the honest framing.

## Does the hash chain make my logs tamper-proof?

**No. It makes them tamper-evident.**

- *Tamper-evident* means an attacker who edits a record and re-saves
  the file will be detected by anyone who runs `verify_chain` and
  knows a trusted prior `chain_hash` head.
- *Tamper-proof* would require write-once / append-only storage (S3
  Object Lock, WORM) or external anchoring (timestamping authority,
  signed receipts).

If your attacker has write access to the storage *and* can recompute
the chain *and* nobody else holds a prior chain head, the chain alone
will not catch it. Pair the chain with one of:

- Object-locked storage so the attacker cannot edit in place.
- Periodic publication of the chain head to a trusted external
  service.
- A signed receipt of the chain head at deployment / shift-end.

This is documented in [`security-model.md`](security-model.md) and
[`trace-stores.md`](trace-stores.md). The library never claims more
than tamper-evident.

## Does `PolicyMetadata.approval_status="approved"` mean the spec is approved?

**No. It means a caller wrote that string into the metadata.** The
library validates that the value is one of `draft / in_review /
approved / deprecated` but does not check signatures, ACLs, or talk
to any approval system. It is metadata — a label your CI/CD writes
when whatever your organisation considers "approved" actually
happens.

To turn it into a real gate, your release pipeline:

1. Computes `policy_checksum(spec)` when a reviewed PR merges.
2. Writes the resulting digest into a metadata file or your deploy
   config alongside `approval_status="approved"`.
3. Refuses to load the spec at runtime if the checksum drifts or the
   status is not `approved`.

The pattern is in [`policy-lifecycle.md`](policy-lifecycle.md).

## Can my agent bypass `sarc-governance`?

**Yes, trivially, if it dispatches a tool without going through
`GovernanceToolset`.** SARC governs the dispatch path it wraps. It is
in-process; it does not stand between an agent process and the
operating system, the network, or any other side-effect channel.

To prevent bypass:

- Make `GovernanceToolset.call_tool` the *only* tool-dispatch path.
  Have one place in the orchestrator that calls it; every other path
  to side-effects (HTTP clients, DB drivers, queue publishers) is
  reached only through tools registered in the wrapped toolset.
- Code-review agents cannot import side-effect libraries directly.
- If the runtime allows model-generated code to execute (e.g. a
  Python REPL tool), that tool itself must be wrapped, and its
  predicate must understand which downstream calls the code can make.

See [`integration-checklist.md`](integration-checklist.md) for the
checklist version of this answer.

## Is the predicate registry safe against malicious specs?

**No more than any other Python module.** Predicates are arbitrary
Python callables registered at import time. Treat the spec — and the
modules that register predicates — as code, not data:

- Do not load specs from untrusted sources.
- Pin the set of importable predicate-registering modules at deploy
  time.
- For richer policy logic against untrusted authors, evaluate in OPA
  / Rego / CEL outside the Python process.

YAML loading itself is `yaml.safe_load`; it does not execute code.
The risk is not the YAML — it is the named predicate the YAML refers
to.

## What happens if my memory backend or escalation handler crashes?

**The library is conservative on the side of safety.** Tested
behaviour:

- Memory backend `add_event` raises → record is dropped, error logged
  at `ERROR` with constraint and action ids, agent loop continues.
  Loss of a trace record never silently turns a deny into an allow.
- Escalation handler raises → exception caught and logged at `ERROR`.
  A hard PAG block still raises `ConstraintViolation`. A failing
  escalation handler **does not** turn a hard block into a pass.

See `tests/test_failure_modes.py` for the assertions and
[`failure-modes.md`](failure-modes.md) for the table of cases.

## How does `audit_trace` differ from `verify_chain`?

They check different invariants on different artefacts:

| Tool | Question it answers | Input |
|---|---|---|
| `audit_trace(spec, trace)` | Did the run evaluate the right constraints, at compatible points, with the spec's declared response? | spec + recorded trace |
| `verify_chain(records)` | Has the trace been edited, reordered, or had records removed since it was written? | chained trace records |

You can run either, both, or neither, depending on what you care
about. CI for a high-stakes deployment should run both: `audit_trace`
catches drift between spec and behaviour, `verify_chain` catches
post-hoc edits to the recorded behaviour.

## Does it work with synchronous tool dispatch?

The `ToolsetProtocol.call_tool` is `async`. If your toolset is
synchronous, wrap each method in `asyncio.to_thread(...)` inside an
adapter `call_tool`, or run the toolset in an executor. The
governance loop does not require true concurrency — it just expects
to `await`.

## Can I run two `GovernanceToolset` instances in parallel?

Yes — give each concurrent agent loop its own instance. The action
counter is local to one instance and is not locked across instances.
For globally unique action ids, replace `_next_action_id` with a
UUID/ULID generator. See the concurrency section of
[`production-hardening.md`](production-hardening.md).

## Where are the limits?

- Constraints are evaluated in spec order. If a hard PAG fires, no
  further PAG constraints are evaluated for that action. (Documented
  in [`failure-modes.md`](failure-modes.md).)
- A `hard` constraint can only sit at PAG or ATM; a `soft` only at
  ATM or PAA; an `escalation` only at PAG or PAA. The compatibility
  table is enforced at construction time. See
  [`architecture.md`](architecture.md).
- The shipped trace stores are single-writer. JSONL appended from two
  processes will corrupt; SQLite serialises writers but is one
  process file.
- Predicates run in the agent loop's event loop. Long-running
  predicates block the loop. Keep them O(args).
