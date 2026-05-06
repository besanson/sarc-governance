# Procurement Agent Example

A runnable end-to-end demo of the SARC enforcement stack against a mock ERP toolset.
No external services or API keys; everything runs in-process.

## What this shows

- Loading a `ConstraintSpec` from YAML with named predicates from the built-in registry.
- Wrapping a plain async toolset with `GovernanceToolset` so PAG / ATM / PAA enforcement
  happens transparently around every `call_tool`.
- A pluggable `EscalationRouter` handler that captures escalation events.
- Auto-persistence of `TraceRecord`s into a `MemoryProtocol`-compliant in-process store.
- Offline conformance checking with `audit_trace`.

## Files

| File | Purpose |
|---|---|
| `sarc_spec.yaml` | Three-constraint spec: hard / escalation / soft |
| `run_demo.py` | Runnable demo: wraps mock toolset, runs 6 scenarios, audits the trace |

## Running

From the repo root, with the package installed (`pip install -e ".[dev]"`):

```bash
python examples/procurement_agent/run_demo.py
```

Only `pyyaml` and the standard library are required.

## Constraints exercised

| ID | Class | Point | Response | Scenario |
|---|---|---|---|---|
| `ch_high_value_po` | hard | PAG | `block_or_escalate` | PO ≥ $50,000 |
| `ce_first_time_supplier` | escalation | PAG | `suspend_route_default_deny` | first-time supplier |
| `cs_rolling_spend` | soft | PAA | `throttle_log` | rolling 24h spend ≥ $475,000 |

## Scenarios

| # | Label | Expected outcome |
|---|---|---|
| 1 | Small order — compliant | `OK` (PO created) |
| 2 | High-value order — PAG hard block | `BLOCKED [ch_high_value_po at PAG]` |
| 3 | First-time supplier — PAG escalation block | escalation routed; `BLOCKED [ce_first_time_supplier at PAG]` |
| 4 | Mid-size order pushing spend past threshold | `OK`; soft constraint flagged at PAA |
| 5 | Tool other than `erp.create_po` | `OK` (no constraint applies) |
| 6 | High-value AND first-time supplier | hard block wins; `BLOCKED [ch_high_value_po at PAG]` |

## Expected output (abridged)

```
============================================================
SARC Procurement Agent Demo
============================================================

Scenario: Small order — compliant
  tool='erp.create_po'  args={'amount': 5000, 'first_time_supplier': False}
  → OK  result={'status': 'created', 'po_id': 'PO-0001', ...}

Scenario: High-value order — PAG hard block
  → BLOCKED  [ch_high_value_po at PAG]

Scenario: First-time supplier — PAG escalation block
    [ER] Escalation routed: constraint=ce_first_time_supplier ...
  → BLOCKED  [ce_first_time_supplier at PAG]

...

============================================================
Audit summary
============================================================
Total trace records in memory: <N>
No discrepancies — trace is SARC-conformant.

Total escalations routed: 2
ERP inner toolset invocations: 3
Final rolling spend: $480,000.00
```

If the audit reports `coverage` discrepancies, that is expected on actions that were
hard-blocked at PAG: when PAG raises before dispatch, ATM/PAA never run, so the
recorded trace for that action is intentionally incomplete. The demo prints a note
explaining this.

## Adapting to your own orchestration layer

If your context object already exposes `ctx.deps.memory` and
`ctx.deps.session_id`, drop the `memory_getter` and `session_id_getter`
overrides — `GovernanceToolset` will auto-detect them:

```python
from sarc_kaos import GovernanceToolset
governed = GovernanceToolset(wrapped=my_toolset, spec=spec)
```

Otherwise, keep the explicit getters as this demo does, or see
[`../../docs/integrations.md`](../../docs/integrations.md) for adapter
patterns for LangGraph, OpenAI tool calling, AWS Bedrock action groups,
and arbitrary async toolsets.
