# Quickstart for developers

A 10-minute path to having `sarc-governance` running against a real
async toolset. This page assumes Python 3.11+ and a Unix-y shell.

## Install

```bash
git clone https://github.com/besanson/sarc-governance.git
cd sarc-governance
pip install -e ".[dev]"
```

The only required runtime dependency is `pyyaml`. Test/dev extras add
`pytest`, `pytest-asyncio`, `ruff`, and `mypy`.

## Verify

```bash
pytest
sarc-governance --version
sarc-governance demo procurement
```

You should see 217 tests passing and the procurement demo printing
six scenarios followed by an audit summary.

## Wrap your first toolset

`GovernanceToolset` wraps any object whose `call_tool` method is
async with this signature:

```python
async def call_tool(self, name: str, args: dict, ctx, tool) -> Any
```

That is the entire integration surface. `ctx` and `tool` are passed
through unchanged to the inner toolset; SARC does not interpret them.

```python
import asyncio
from sarc_governance import (
    Constraint, ConstraintSpec, GovernanceToolset,
    ConstraintViolation,
)

class MyToolset:
    async def call_tool(self, name, args, ctx, tool):
        return {"status": "ok", "tool": name, "args": args}

spec = ConstraintSpec(constraints=[
    Constraint(
        id="block_high_value",
        klass="hard",
        verif="PAG",
        response="block_or_escalate",
        predicate=lambda ctx: (
            ctx["tool"] == "create_po"
            and ctx["args"].get("amount", 0) >= 50_000
        ),
    ),
])

governed = GovernanceToolset(wrapped=MyToolset(), spec=spec)

async def main():
    print(await governed.call_tool("create_po", {"amount": 1_000}))
    try:
        await governed.call_tool("create_po", {"amount": 75_000})
    except ConstraintViolation as exc:
        print(f"blocked: {exc.constraint_id} at {exc.point.value}")

asyncio.run(main())
```

## Move the spec to YAML

Predicates referenced from YAML are resolved by name from the
predicate registry — there is no `eval` or `exec`.

```python
# my_predicates.py
from sarc_governance.predicates import register

@register("is_high_value_po")
def _is_high_value_po(ctx):
    return ctx["tool"] == "create_po" and ctx["args"].get("amount", 0) >= 50_000
```

```yaml
# spec.yaml
constraints:
  - id: block_high_value
    class: hard
    verif: PAG
    response: block_or_escalate
    predicate: is_high_value_po
    description: Block POs at or above $50,000.
```

```python
import my_predicates  # noqa: F401  — register-side-effect import
from sarc_governance import load_spec
spec = load_spec("spec.yaml")
```

`sarc-governance validate spec.yaml` will reject unknown predicate
names and incompatible class/point pairs at CI time.

## Persist trace records

The runtime emits one `TraceRecord` per `(action, constraint, point)`
triple. To capture them, give `GovernanceToolset` either:

1. A `ctx` whose `ctx.deps.memory` is a `MemoryProtocol` and
   `ctx.deps.session_id` is a string — auto-detected; nothing else to
   wire; **or**
2. Explicit `memory_getter=` / `session_id_getter=` callables; **or**
3. Use one of the shipped trace stores via a thin adapter:

```python
from sarc_governance import GovernanceToolset, JSONLTraceStore

class StoreBackedMemory:
    def __init__(self, store): self._store = store
    async def add_event(self, session_id, event_type, content, metadata=None):
        if event_type == "governance_event":
            self._store.append(content, session_id=session_id)

store = JSONLTraceStore("trace.jsonl", hash_chain=True)
memory = StoreBackedMemory(store)

class Ctx:
    class Deps:
        def __init__(self, memory, session_id):
            self.memory = memory
            self.session_id = session_id
    def __init__(self, memory, session_id):
        self.deps = Ctx.Deps(memory, session_id)

governed = GovernanceToolset(wrapped=MyToolset(), spec=spec)
await governed.call_tool("create_po", {"amount": 1000}, ctx=Ctx(memory, "sess-1"))
```

After the run:

```bash
sarc-governance trace verify-chain trace.jsonl
sarc-governance audit spec.yaml trace.jsonl
```

## Wire the CI gate

```yaml
# .github/workflows/governance.yml (illustrative)
- run: sarc-governance validate config/spec.yaml
- run: sarc-governance policy inspect config/spec.yaml --json
- run: sarc-governance policy diff main:config/spec.yaml HEAD:config/spec.yaml --exit-code
- run: pytest
- run: python scripts/run_smoke.py --dump trace.jsonl
- run: sarc-governance trace verify-chain trace.jsonl
- run: sarc-governance audit config/spec.yaml trace.jsonl
```

`policy diff --exit-code` is a "force human review" gate; remove it if
your workflow expects auto-merge of constraint edits.

## Read next

- [Mental model](mental-model.md) — what this library is and is not.
- [Integration checklist](integration-checklist.md) — required
  decisions before shipping.
- [Spec authoring](spec-authoring.md) — YAML schema, predicate
  registry, common mistakes.
- [Audit traces](audit-traces.md) — invariants checked, trace shapes,
  CLI workflow.
- [Trace stores](trace-stores.md) — choosing JSONL vs SQLite, hash
  chain semantics.
- [Policy lifecycle](policy-lifecycle.md) — checksum, diff, approval
  metadata.
- [Security model](security-model.md) — threat model, what is and is
  not protected.
- [Failure modes](failure-modes.md) — runtime behaviour on memory /
  escalation / spec / store errors.
- [Production hardening](production-hardening.md) — what is still on
  you before a critical path.
