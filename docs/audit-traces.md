# Auditing SARC traces

`audit_trace(spec, trace)` checks a recorded run against a spec for the
three SARC invariants:

| Invariant | What it checks |
|---|---|
| I1 — coverage | Every spec constraint was evaluated for every action. |
| I2 — placement | Each constraint was evaluated only at points compatible with its class. |
| I3 — response | Each fired constraint used the spec-declared response. |

A fourth check, **attribution completeness**, applies to the action-level
schema only and is on by default.

## Trace shapes

`audit_trace` (and `sarc-governance audit`) accept two trace shapes and
auto-detect which is which:

### 1. Flat `TraceRecord` list

Native output of `GovernanceToolset`. One record per
`(action_id, constraint_id, point)` triple.

```json
[
  {
    "action_id": "act-1",
    "tool": "erp.create_po",
    "point": "PAG",
    "constraint_id": "ch_high_value_po",
    "class": "hard",
    "fired": false,
    "response": "block_or_escalate",
    "timestamp": 1700000000.0
  }
]
```

### 2. Action-level schema (`benchmarks/sarc_eval.py`)

One record per action, with an `evaluated` array containing per-constraint
sub-records. Used by the paper benchmark pipeline.

```json
[
  {
    "action_id": "act-1",
    "state": {...},
    "action": {...},
    "evaluated": [
      {"id": "ch_high_value_po", "verif": "PAG", "fired": false, "response": "block_or_escalate"}
    ],
    "attribution": {"authority_nonempty": true}
  }
]
```

## Capturing a trace

The simplest way is to give `GovernanceToolset` a `MemoryProtocol` and
dump its events at the end of a run:

```python
import json
from sarc_governance import GovernanceToolset, audit_trace

# memory.governance_events(session_id) returns a list of TraceRecord dicts.
trace = memory.governance_events(session_id)
pathlib.Path("trace.json").write_text(json.dumps(trace, indent=2))
```

The bundled `procurement_agent` demo includes an in-process memory shim
that does exactly this.

## Auditing from the CLI

```bash
sarc-governance audit spec.yaml trace.json
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | No discrepancies, or `--allow-discrepancies` was passed. |
| `1` | Discrepancies found, or invalid spec/trace. |
| `2` | File not found. |

Useful flags:

| Flag | Effect |
|---|---|
| `--allow-discrepancies` | Print the report but exit `0`. |
| `--no-attribution` | Skip the attribution check (action-level traces only). |

## Worked example

See [`examples/audit_trace_file/`](../examples/audit_trace_file/README.md):

```bash
# pass
sarc-governance audit examples/audit_trace_file/spec.yaml \
                examples/audit_trace_file/trace_pass.json
# audit: PASS  (no discrepancies)   -> exit 0

# fail (placement + response + coverage)
sarc-governance audit examples/audit_trace_file/spec.yaml \
                examples/audit_trace_file/trace_fail.json
# audit: FAIL  (3 discrepancies)    -> exit 1
```

## Coverage on blocked actions

When a hard PAG constraint fires, the inner toolset is never invoked and
PAA records are never emitted. The auditor flags the missing PAA
evaluations as coverage discrepancies — this is correct behavior.

If you need a "clean" audit for runs that include blocks, filter
discrepancies of type `coverage` whose `action_id` corresponds to a
blocked action, or use `--allow-discrepancies` and inspect the report by
type.

## CI pattern

```yaml
# .github/workflows/governance.yml (illustrative)
- run: sarc-governance validate config/spec.yaml
- run: python scripts/run_smoke.py --dump trace.json
- run: sarc-governance audit config/spec.yaml trace.json
```

`validate` gates on spec syntax; `audit` gates on runtime conformance of a
representative smoke run.
