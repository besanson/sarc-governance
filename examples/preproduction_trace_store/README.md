# Pre-production trace store example

End-to-end demo that exercises the pre-production foundations on top of
the procurement spec:

- `PolicyMetadata` + `policy_checksum` for content fingerprinting
- `SQLiteTraceStore(hash_chain=True)` for durable, tamper-evident traces
- `ExecutionContext` auto-stamped onto every record
- `verify_chain` to detect tampering
- `export_jsonl` to ship records to an external tool
- `diff_policies` to surface intentional spec changes

## Run

```bash
python examples/preproduction_trace_store/run_demo.py
```

The script writes `trace.sqlite` and `trace.jsonl` next to itself. Both
are safe to delete; each run starts from a clean slate.

## What the script does

1. Loads `examples/procurement_agent/sarc_spec.yaml`.
2. Wraps the spec with `PolicyMetadata(approval_status="approved", ...)`
   and prints the checksum.
3. Wires a `SQLiteTraceStore` into a `GovernanceToolset` via a tiny
   `MemoryProtocol` adapter.
4. Runs three governed tool calls — the third trips the `hard / PAG`
   block on high-value POs.
5. Reads back every record from the store and verifies the hash chain.
6. Exports the store to JSONL and verifies the chain on the export.
7. Simulates a downgrade of the escalation response and prints the
   structured `diff_policies` output.

## CLI smoke commands the demo enables

After running the script you can inspect the artefacts with the CLI:

```bash
sarc-governance trace verify-chain examples/preproduction_trace_store/trace.jsonl
sarc-governance policy inspect examples/procurement_agent/sarc_spec.yaml
```

## What this demo does *not* show

- **Multi-process writers.** All three stores are single-writer.
  Multiple processes appending to the same file or DB will race; bring
  a real durable backend if that is your topology.
- **Signed approval.** `PolicyMetadata.approval_status` is a string —
  the library does not check signatures. CI/CD enforces what
  "approved" means.
- **External anchoring.** The chain is tamper-evident, not
  tamper-proof. Pair with write-once storage or a timestamping
  authority for stronger guarantees. See
  [`docs/security-model.md`](../../docs/security-model.md).
