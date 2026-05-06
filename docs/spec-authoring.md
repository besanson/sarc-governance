# Authoring SARC constraint specs

A constraint spec is a list of `Constraint` declarations. It can be
authored in Python or loaded from YAML/JSON. The loader resolves
`predicate` strings through the registry in `sarc_governance.predicates`; no
`eval` or `exec` is used.

## YAML schema

```yaml
constraints:
  - id: ch_high_value_po
    class: hard               # hard | soft | escalation
    verif: PAG                # PAG | ATM | PAA
    response: block_or_escalate
    predicate: is_high_value_po
    description: Block POs >= $50,000 before ERP dispatch.
```

Required keys: `id`, `class`, `verif`, `response`, `predicate`. The
`description` field is optional but recommended — it surfaces in
`sarc-governance validate` output.

## Class × point rules

| Class | Allowed points |
|---|---|
| `hard` | `PAG`, `ATM` |
| `soft` | `ATM`, `PAA` |
| `escalation` | `PAG`, `PAA` |

Violations raise `ValueError` at `Constraint(...)` time and are also
checked offline by `audit_trace` (placement discrepancy).

## Responses

Use the canonical strings from `Response`:

- `block`
- `block_or_escalate`
- `throttle_log`
- `escalate`
- `suspend_route_default_deny`
- `log`

The runtime does not interpret most of these — they are recorded in
`TraceRecord.response` so external systems and `audit_trace` can compare
them against the spec. The runtime does interpret `block`,
`block_or_escalate`, and `suspend_route_default_deny` at PAG: any of these
fires raise `ConstraintViolation` and skip the inner call.

## Writing predicates

A predicate is a callable `(ctx: dict) -> bool`. The shape of `ctx` depends
on the enforcement point:

| Point | `ctx` keys |
|---|---|
| `PAG` | `tool`, `args` |
| `ATM` | `tool`, `args`, `result`, `elapsed` |
| `PAA` | `tool`, `args`, `result` |

Built-in predicates live in `sarc_governance.predicates`. List them with:

```bash
sarc-governance list-predicates
```

Register your own:

```python
from sarc_governance.predicates import register

@register("blocks_external_email")
def _blocks_external_email(ctx):
    if ctx["tool"] != "send_email":
        return False
    return not ctx["args"].get("to", "").endswith("@example.com")
```

Then reference by name in YAML: `predicate: blocks_external_email`.

For *ad-hoc* tests or one-off scripts, pass `extra_predicates=` to
`load_spec`:

```python
spec = load_spec(
    "spec.yaml",
    extra_predicates={"in_test": lambda ctx: True},
)
```

`extra_predicates` shadow the global registry but are not persisted across
calls.

## Validating from the command line

```bash
sarc-governance validate path/to/spec.yaml
```

Prints a per-constraint table (id / class / point / response). Exits
non-zero on structural errors or unknown predicate names — usable in CI as
a pre-merge gate on spec changes.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `ValueError: class='hard' cannot be verified at 'PAA'` | `hard` is only allowed at PAG/ATM. | Either move the constraint to PAG/ATM or change class to `soft`/`escalation`. |
| `ValueError: No predicate registered under '...'` | Predicate name is a typo or the module that calls `register(...)` was never imported. | Import the module before `load_spec`, or pass it via `extra_predicates`. |
| Audit reports `coverage` discrepancies for blocked actions | Hard PAG block prevents PAA records from being emitted; the audit invariant treats this as missing coverage. | Expected for blocked actions. Use `--allow-discrepancies` or filter. |
| Predicate fires on the wrong action | `ctx["tool"]` mismatch — predicate didn't gate by tool name. | Add an early `if ctx["tool"] != "...": return False`. |
| Spec roundtrip fails | A constraint references a callable directly. | Predicate values in YAML must be names; register the function and use its name. |

## Building specs in Python

For tests, you usually do not want to touch YAML at all:

```python
from sarc_governance import Constraint, ConstraintSpec

SPEC = ConstraintSpec(
    constraints=[
        Constraint(
            id="ch_refund_cap",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=lambda ctx: ctx["tool"] == "refund" and ctx["args"]["amount"] > 1000,
        ),
    ]
)
```

The same validation runs (compatibility check, duplicate-id check), and
the result is interchangeable with a YAML-loaded spec.
