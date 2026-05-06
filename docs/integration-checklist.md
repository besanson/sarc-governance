# Integration checklist

A concrete checklist for putting `sarc-governance` in front of a real
toolset. Items are grouped by the question they answer. None of these
is a SARC research question — they are operational decisions every
adopter must make.

For the rationale behind each item, see [`mental-model.md`](mental-model.md),
[`security-model.md`](security-model.md), and
[`production-hardening.md`](production-hardening.md).

## 1. Wrap the dispatch boundary — and only the dispatch boundary

- [ ] Every code path that has a side-effect on the world (DB write,
      HTTP call, queue publish, FS write, payment, message send) is
      reachable only through a tool that is exposed by the wrapped
      `ToolsetProtocol`.
- [ ] No code path in the agent imports an HTTP client, DB driver,
      queue client, or AWS SDK directly. Side-effect SDKs live behind
      tool functions, never as modules the agent code can `import`.
- [ ] There is exactly *one* `GovernanceToolset.call_tool` invocation
      site per concurrent agent. (Otherwise a future contributor will
      add an "unimportant" call that bypasses the gates.)
- [ ] If the runtime allows model-generated code to execute (a Python
      REPL tool, a shell tool), that tool itself is wrapped and its
      predicate understands the downstream calls it can produce.
- [ ] If multiple agent loops run concurrently, each has its own
      `GovernanceToolset` instance.

## 2. Persist the trace

- [ ] A `MemoryProtocol` implementation is supplied to
      `GovernanceToolset` (via `ctx.deps.memory`, an explicit
      `memory_getter`, or one of the shipped trace stores wrapped
      behind a thin `MemoryProtocol` adapter).
- [ ] A `session_id` is provided per agent run so traces from
      different sessions are separable.
- [ ] The persistence target is appropriate for your topology:
      - Single-writer file → `JSONLTraceStore`.
      - Multi-session local retention → `SQLiteTraceStore`.
      - Multi-process or networked → bring your own backend
        (relational DB, queue, log shipper). The shipped stores are
        single-writer.
- [ ] A retention policy exists (how many days, who deletes, where it
      lands long-term).
- [ ] If a tamper-evident audit trail is required, `hash_chain=True`
      is enabled on the store *and* the chain head is anchored
      somewhere outside the same writer (signed daily, written to
      object-locked storage, or published to a timestamping
      authority). The chain alone is *evident*, not *proof*.

## 3. Wire identity in

- [ ] Every governed call carries an `ExecutionContext` with at
      minimum `principal_id`, `tenant_id`, `agent_id`, `session_id`,
      and `environment`. Without these, predicates cannot make
      identity-aware decisions and traces cannot be attributed.
- [ ] Predicates that gate on identity read from
      `ctx["execution_context"]` (PAG / ATM / PAA all carry it when
      stamped) rather than guessing from `args`.
- [ ] Roles are populated from your auth layer, not hard-coded in the
      spec.

## 4. Replace the default escalation router

- [ ] `EscalationRouter(handler=...)` is constructed with a real
      handler. The default `log only` is acceptable for tests, demos,
      and non-critical paths — not for anything that gates real
      decisions.
- [ ] The handler writes to durable storage (queue, ticket system,
      pager) so a process restart does not lose pending escalations.
- [ ] The handler is wrapped in `asyncio.wait_for(...)` (or a
      framework-equivalent) so a hung downstream cannot stall the
      agent loop indefinitely.
- [ ] The "human approves out-of-band" pattern uses a paired
      `escalation`/PAG + `hard`/PAG ledger constraint, as in
      [`examples/human_escalation/`](../examples/human_escalation/README.md).
      `EscalationRouter` only routes — a hard constraint reading the
      ledger is what actually gates execution.

## 5. Put the policy under change control

- [ ] The spec lives in version control (git, signed artefacts in
      object store) and changes go through PR review.
- [ ] CI runs `sarc-governance validate` and
      `sarc-governance policy diff base:HEAD --exit-code` on every
      PR, so structural errors and silent edits surface to the
      reviewer.
- [ ] The release pipeline records `policy_checksum(spec)` in
      `PolicyMetadata` at the moment of approval and refuses to load
      a spec whose runtime checksum drifts from the recorded one.
- [ ] `PolicyMetadata.approval_status` is set programmatically by the
      release pipeline, not edited by hand. (The library does not
      validate signatures.)
- [ ] The runtime aborts on `approval_status != "approved"` if the
      deployment is on a critical path.

## 6. Run the audit gate

- [ ] CI runs a representative smoke run of the agent against a
      seed prompt, dumps the trace, and runs `sarc-governance audit
      spec.yaml trace.json` as a gating step.
- [ ] CI runs `sarc-governance trace verify-chain trace.jsonl` if the
      hash chain is enabled.
- [ ] Coverage discrepancies on hard-blocked actions are filtered or
      acknowledged (PAA is intentionally not reached when PAG
      raises).

## 7. Test the failure modes

- [ ] A test asserts that a memory backend that raises does not break
      the agent loop and does not turn a deny into an allow.
- [ ] A test asserts that an escalation handler that raises does not
      turn a hard PAG block into a pass.
- [ ] A test asserts that an unknown predicate name in the spec
      raises `ValueError` at load time, before any agent runs.
- [ ] (Optional) A periodic test mutates a record in a chained trace
      and verifies that `verify_chain` reports a `record_hash_mismatch`.

## 8. Observability

- [ ] At minimum, counters per `(constraint_id, point, fired)` are
      emitted to your metrics system (the library does not depend on
      OpenTelemetry; an exporter against the trace store protocol is
      a few dozen lines).
- [ ] A dashboard exists for "blocks per minute" and "escalations per
      minute" with alerting on either silence (predicate has rotted)
      or a spike (something changed upstream).
- [ ] Trace records from the same `request_id` / `session_id` are
      retrievable by a single query (this is what
      `ExecutionContext.request_id` is for).

## 9. Performance budget

- [ ] Predicate cost has been measured against the worst-case input
      size you actually see. SARC does not throttle the constraint
      list — every PAG/ATM/PAA constraint runs every call.
- [ ] Tail latency under load has been tested with the production
      spec and tool mix, especially p99 with PAA constraints in the
      loop.
- [ ] Failure injection has been exercised: handler exceptions,
      memory backend stalls.

## 10. Bypass review

The single highest-leverage question to ask before shipping is:

> *"Where in this codebase can a future contributor make a side-effect
> happen without calling `GovernanceToolset.call_tool`?"*

If the honest answer is "many places", the gate is decorative. The
checklist above exists to make the answer "exactly the wrapped
toolset, by construction". Run that audit before each rollout.
