# Command-line interface

```bash
sarc-governance validate examples/procurement_agent/sarc_spec.yaml
sarc-governance list-predicates
sarc-governance audit  examples/audit_trace_file/spec.yaml \
                  examples/audit_trace_file/trace_pass.json
sarc-governance policy inspect examples/procurement_agent/sarc_spec.yaml
sarc-governance policy diff old_spec.yaml new_spec.yaml --exit-code
sarc-governance trace verify-chain trace.jsonl
sarc-governance trace export trace.sqlite trace.jsonl
sarc-governance demo procurement
```

`audit`, `policy diff --exit-code`, and `trace verify-chain` exit non-zero on
discrepancies, making them CI-friendly. See
[audit-traces.md](audit-traces.md) for the trace schema and
[policy-lifecycle.md](policy-lifecycle.md) for the policy commands.
