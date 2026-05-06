# Audit a SARC trace file

This example shows how to use the `sarc-kaos audit` CLI to gate CI on the
SARC conformance of a recorded run.

## Files

| File | What it is |
|---|---|
| `spec.yaml` | Two constraints: one hard PAG and one soft PAA. |
| `trace_pass.json` | A trace where both constraints were evaluated at the right point with the right response. |
| `trace_fail.json` | A trace with three deliberate discrepancies (placement, response, coverage). |
| `run_audit.sh` | Runs both audits and prints exit codes. |

## Run it

```bash
sarc-kaos audit examples/audit_trace_file/spec.yaml \
                examples/audit_trace_file/trace_pass.json
# audit: PASS  (no discrepancies)   — exit 0

sarc-kaos audit examples/audit_trace_file/spec.yaml \
                examples/audit_trace_file/trace_fail.json
# audit: FAIL  (3 discrepancies)    — exit 1
#   placement: 1
#   response:  1
#   coverage:  1
```

To capture a trace from your own run, persist `TraceRecord.to_dict()` for
every governance event (the `examples/procurement_agent/run_demo.py` demo
does this via an in-process `MemoryProtocol` shim) and dump the list to
JSON.

## Using `--allow-discrepancies`

For exploratory runs where coverage gaps are expected (a `hard/PAG` block
prevents PAA records from being emitted), pass `--allow-discrepancies` to
print the report without exiting non-zero:

```bash
sarc-kaos audit spec.yaml trace_fail.json --allow-discrepancies
echo $?  # 0
```

## Schema notes

The CLI accepts two trace shapes (auto-detected):

1. **Flat trace records** — list of `TraceRecord` dicts emitted by
   `GovernanceToolset`. Required keys: `action_id`, `tool`, `point`,
   `constraint_id`, `class`, `fired`, `response`. Optional: `timestamp`,
   `extra`.
2. **Action-level records** (the `benchmarks/sarc_eval.py` schema) — list
   of action dicts with an `evaluated` array and an `attribution` block.
   Use `--no-attribution` to skip the attribution check.
