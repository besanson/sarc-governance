# Failure modes

A short reference for what `sarc-governance` does when things go wrong
at runtime. The full discussion lives in
[`security-model.md`](security-model.md); this page is the cheat sheet.

| Failure | Library behaviour | Test |
|---|---|---|
| Memory backend raises on `add_event` | Log at ERROR, drop the record, continue. Never silently turns deny into allow. | `tests/test_failure_modes.py::test_failing_memory_does_not_break_agent_loop` |
| Escalation handler raises | Log at ERROR, suppress. Hard PAG block *still* raises `ConstraintViolation`. | `tests/test_failure_modes.py::test_failing_escalation_handler_does_not_silently_pass_a_hard_block` |
| Wrapped tool raises | Exception propagates; PAA is skipped (no result to audit). | covered by `tests/test_governance.py` |
| Unknown predicate in spec | `load_spec` raises `ValueError` before any call runs. CLI returns exit code 1. | `tests/test_failure_modes.py::test_unknown_predicate_raises_valueerror` |
| Malformed spec | `load_spec` raises `ValueError`. CLI returns exit code 1. | `tests/test_failure_modes.py::test_malformed_spec_top_level_raises` |
| Corrupted JSONL line in trace | Store skips the line on iteration; `verify_chain` will then detect a `prev_hash_mismatch` for the next record. | `tests/test_stores.py::test_jsonl_store_skips_corrupted_lines` |
| Trace store payload tampered after-the-fact | `verify_chain` returns a `record_hash_mismatch` break. | `tests/test_stores.py::test_sqlite_chain_break_detected_on_payload_tamper` |
| Escalation timeout (handler hangs) | Not handled by the library — `await` blocks. Wrap your handler with `asyncio.wait_for` to bound it. | (responsibility of caller) |

## Configuration knobs

- `EscalationRouter(handler=fn)` — pluggable async handler. Default is
  log-only. Wrap with `asyncio.wait_for(handler(...), timeout=N)` for a
  bounded escalation.
- `GovernanceToolset(stamp_context=False)` — disable `ExecutionContext`
  injection into trace records. Useful if your records flow through a
  PII-sensitive pipeline.
- `*TraceStore(hash_chain=True)` — opt-in tamper-evident chaining.

## What is intentionally *not* configurable

- **Hard PAG block raises before the inner call.** This is the contract
  of `hard` constraints — there is no "warn but allow" mode at PAG.
- **PAA runs after a successful call only.** If you need to audit
  failed calls, capture the exception in your wrapped toolset and emit
  a result that PAA can read.
- **The order of constraint evaluation is the order in the spec.** If
  one PAG-hard fires, no further PAG constraints are evaluated for that
  action. Order your specs accordingly.
