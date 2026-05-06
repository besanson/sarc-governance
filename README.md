# sarc-kaos

**SARC** (Specification-Adherent Runtime Constraints) governance layer, designed to wrap
[KAOS](https://github.com/kaos-project/kaos) / pydantic-ai toolsets and any compatible
async toolset via minimal Protocols.

> This is the standalone reference implementation of the SARC architecture described in
> *"SARC: A Runtime Governance Architecture for Tool-Using Agentic AI Systems"*
> (see [`paper/`](paper/README.md)).

---

## Concepts

SARC treats constraints as **first-class governance objects** rather than ad hoc checks:

| Concept | Description |
|---|---|
| **ConstraintClass** | `hard` · `soft` · `escalation` |
| **EnforcementPoint** | `PAG` (Pre-Action Gate) · `ATM` (Action-Time Monitor) · `PAA` (Post-Action Auditor) · `ER` (Escalation Router) |
| **ConstraintSpec** | Validated, immutable bundle of constraints; drives enforcement and audit |
| **GovernanceToolset** | Wraps any async toolset; enforces constraints at PAG/ATM/PAA |
| **EscalationRouter** | Pluggable async handler; default is structured logging |
| **audit_trace** | Checks coverage, placement, response, and attribution of a recorded trace |

### Class-to-point compatibility (paper §4.2, Table 1)

| Class | Allowed points |
|---|---|
| `hard` | PAG, ATM |
| `soft` | ATM, PAA |
| `escalation` | PAG, PAA |

---

## Installation

```bash
pip install -e ".[dev]"
```

Dependencies: **pyyaml** + stdlib only (no pydantic-ai required to use the core package;
it is needed only if you wrap an actual KAOS/pydantic-ai toolset).

---

## Quick start

```python
import asyncio
from sarc_kaos import Constraint, ConstraintSpec, GovernanceToolset, EscalationRouter

spec = ConstraintSpec(constraints=[
    Constraint(
        id="ch_high_value_po",
        klass="hard",
        verif="PAG",
        response="block_or_escalate",
        predicate=lambda ctx: ctx["tool"] == "erp.create_po" and ctx["args"].get("amount", 0) >= 50_000,
        description="Block purchase orders ≥ $50 000 before dispatch",
    ),
])

toolset = GovernanceToolset(wrapped=my_toolset, spec=spec)
# Use toolset.call_tool(...) — PAG, ATM, and PAA enforcement is automatic.
```

See [`examples/procurement_agent/`](examples/procurement_agent/README.md) for a runnable demo.

---

## Spec loading from YAML

```python
from sarc_kaos.specs import load_spec

spec = load_spec("examples/procurement_agent/sarc_spec.yaml")
```

Named predicates from the built-in registry are resolved by name; custom predicates can
be registered via `sarc_kaos.predicates.register`.

---

## Audit

```python
from sarc_kaos.audit import audit_trace

discrepancies = audit_trace(spec, trace_records)
# discrepancies is [] if and only if the trace is SARC-conformant.
```

Discrepancy types: `coverage` · `placement` · `response` · `attribution`.

---

## Running tests

```bash
pytest
```

---

## Benchmarks

Pre-computed results from the SARC paper evaluation live in [`benchmarks/`](benchmarks/README.md).
Run `python benchmarks/sarc_eval.py` to regenerate.

---

## Paper

The LaTeX source is in [`paper/`](paper/README.md).
