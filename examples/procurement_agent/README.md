# Procurement Agent Example

This example demonstrates the full SARC enforcement stack against a mock ERP toolset.

## Files

| File | Purpose |
|---|---|
| `sarc_spec.yaml` | Three-constraint spec: hard, escalation, soft |
| `run_demo.py` | Runnable demo: wraps mock toolset, runs 6 scenarios, audits trace |

## Running

From the repo root:

```bash
python examples/procurement_agent/run_demo.py
```

No external dependencies beyond `pyyaml` (already in `pyproject.toml`).

## Constraints exercised

| ID | Class | Point | Response | Scenario |
|---|---|---|---|---|
| `ch_high_value_po` | hard | PAG | `block_or_escalate` | PO ≥ $50 000 |
| `ce_first_time_supplier` | escalation | PAG | `suspend_route_default_deny` | first-time supplier |
| `cs_rolling_spend` | soft | PAA | `throttle_log` | rolling 24h spend ≥ $475 000 |

## Expected output (abridged)

```
Scenario: Small order — compliant
  → OK  result={'status': 'created', ...}

Scenario: High-value order — PAG hard block
  → BLOCKED  [ch_high_value_po at PAG]

Scenario: First-time supplier — PAG escalation block
    [ER] Escalation routed: constraint=ce_first_time_supplier ...
  → BLOCKED  [ce_first_time_supplier at PAG]

Audit summary
No discrepancies — trace is SARC-conformant.
```

## Adapting to KAOS / pydantic-ai

Replace `ERPToolset` with your `AbstractToolset` subclass and remove the
`memory_getter` / `session_id_getter` overrides — the toolset auto-detects
KAOS `AgentDeps` from `ctx.deps.memory` and `ctx.deps.session_id`.

```python
from pais.tools import DelegationToolset
toolset = GovernanceToolset(wrapped=DelegationToolset(...), spec=spec)
```
