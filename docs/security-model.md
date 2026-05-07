# Security model and failure modes

What `sarc-governance` does and does not protect against. Use this page
to set expectations before deploying.

## Threat model

The library protects against:

1. **Faulty agent code** placing tool calls that violate declared
   constraints — caught at PAG / ATM and either blocked (hard) or
   routed (escalation).
2. **Inadvertent drift in a spec** — `policy_checksum` plus
   `policy diff` flag changes; CI gating refuses to load drifted specs.
3. **Silent loss of audit data** — durable trace stores write to disk
   (JSONL / SQLite); the hash chain detects record tampering, removal,
   or reordering after the fact.

The library does **not** protect against:

1. **An attacker with code-execution on the host running the agent.**
   Constraints, predicates, and trace stores all run in the same
   process. There is no sandbox.
2. **A spec author who can register a malicious predicate.** Predicates
   are arbitrary Python; the predicate registry is loaded at import
   time. **Mitigation**: use `safe_load_spec` (see below) so specs loaded
   at runtime can only reference predicates already in the registry — no
   callable injection from untrusted config paths.
3. **Storage tampering.** The hash chain is *tamper-evident* — an
   attacker with write access can rebuild the chain after editing. For
   tamper-proofness you need write-once / append-only storage or an
   external anchor (timestamping authority, blockchain receipt).
4. **Network attacks against escalation handlers.** Whatever ticketing
   / paging system the handler talks to is your problem.
5. **Spec confidentiality.** Specs are loaded plaintext; encrypt at
   rest if your constraints are sensitive.

## Failure modes the library handles

The runtime is conservative on the side of safety. The contract is:

- **Memory backend raises on `add_event`.** The trace record is dropped,
  the failure is logged at `ERROR` with constraint and action ids, and
  the agent loop continues. Loss of a trace record never blocks an
  action *and* never silently turns a deny into an allow.
  ([test](../tests/test_failure_modes.py))
- **Escalation handler raises.** The exception is caught and logged at
  `ERROR` by `EscalationRouter`. The originating constraint's behaviour
  is preserved: a hard PAG block still raises `ConstraintViolation`; an
  escalation-class constraint that *only* routes still completes the
  inner call. A failing escalation handler **does not** turn a hard
  block into a pass. ([test](../tests/test_failure_modes.py))
- **Inner tool call raises.** The exception propagates up; PAA is
  skipped (since there is no result to audit). PAG records are already
  emitted. ATM records are not, because the call did not return.
- **Unknown predicate name in spec.** `load_spec` raises `ValueError`
  before any agent runs.
- **Malformed YAML / JSON spec.** `load_spec` raises `ValueError`. The
  CLI returns exit code 1.
- **Corrupted JSONL line.** Stores skip the line during iteration.
  Verification will then report a `prev_hash_mismatch` for the next
  chained record (so silent loss is still detected).

## What is *not* handled and is your responsibility

- **Default-deny on unknown tool.** SARC enforces declared constraints
  on tools it sees; if your toolset is dynamic, your dispatch layer must
  reject unknown tools first.
- **Rate limiting.** Neither tool calls nor escalations are rate
  limited. A predicate firing on every call will produce one record
  per call. Add throttling in your memory backend or escalation
  handler.
- **Replay protection on traces.** Records carry a timestamp but not a
  monotonic counter across instances. If you run multiple
  `GovernanceToolset` instances, do not assume action ids are globally
  unique. Use `ExecutionContext.request_id` for cross-instance
  correlation.
- **Approval enforcement.** `PolicyMetadata.approval_status` is a
  string. CI/CD enforces what `approved` means.

## `safe_load_spec` — the recommended production loading path

`load_spec` accepts an `extra_predicates` dict that allows application code
to inject arbitrary callables alongside a YAML file. This is useful in tests
but is a callable-injection vector in production.

`safe_load_spec(path)` is the narrower alternative:

- Accepts only file paths (not raw dicts assembled at runtime).
- Does not accept `extra_predicates`.
- All predicate names must be in the global registry before the call.

```python
from sarc_governance import safe_load_spec
from sarc_governance.predicates import register

@register("my_predicate")
def my_predicate(ctx): ...     # registered at import time, not at load time

spec = safe_load_spec("/config/sarc_spec.yaml")   # only registry predicates
```

Use `safe_load_spec` everywhere your spec comes from a ConfigMap, an external
config system, or any path that is not your own reviewed application code.
Reserve `load_spec(..., extra_predicates=...)` for tests and trusted tooling.

## When to escalate the threat model

If your deployment is on a regulated path (PCI, HIPAA, SOX), assume the
items above are *necessary but not sufficient*. You will additionally
need:

- A signed and dated bundle of the spec at the moment of approval.
- Append-only storage for the trace (object lock on S3, WORM tape,
  or a blockchain receipt for the chain head).
- A reviewer audit trail tying every escalation outcome back to a named
  individual.

The library exposes the seams (`MemoryProtocol`, `EscalationHandler`,
`ExecutionContext`) so those systems can be plugged in without changing
the core.
