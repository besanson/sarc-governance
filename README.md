# sarc-kaos

A runtime governance layer that wraps any async toolset and enforces declarative
constraints (hard / soft / escalation) at three in-process points around every tool call.

> **Status:** developer toolkit / reference implementation of the SARC architecture
> from *"SARC: A Runtime Governance Architecture for Tool-Using Agentic AI Systems"*
> ([`paper/`](paper/README.md)). Suitable for prototypes, evaluation, and serious POCs;
> see [docs/production-hardening.md](docs/production-hardening.md) for what's still
> needed before a production deployment.

## Documentation

- [Architecture](docs/architecture.md) — SARC loop, components, class × point compatibility.
- [Spec authoring](docs/spec-authoring.md) — YAML schema, predicates, common mistakes.
- [Audit traces](docs/audit-traces.md) — trace shapes, `audit_trace` semantics, CI workflow.
- [Integrations](docs/integrations.md) — KAOS, LangGraph-style, OpenAI tool calling, AWS Bedrock action groups, generic.
- [Production hardening](docs/production-hardening.md) — persistence, observability, auth, perf, CI/CD.

## Command-line interface

```bash
sarc-kaos validate examples/procurement_agent/sarc_spec.yaml
sarc-kaos list-predicates
sarc-kaos audit  examples/audit_trace_file/spec.yaml \
                  examples/audit_trace_file/trace_pass.json
sarc-kaos demo procurement
```

`audit` exits non-zero on discrepancies (override with `--allow-discrepancies`),
making it CI-friendly. See [docs/audit-traces.md](docs/audit-traces.md) for the
trace schema.

---

## Framework-agnostic by design

**`sarc-kaos` does not import KAOS, pydantic-ai, LangGraph, OpenAI, or boto3 / Bedrock.**
None of them are required to be installed. The package is framework-neutral and
depends only on `pyyaml` plus the standard library. SARC-KAOS is the *governance
layer*; orchestration is whatever you already use.

What it does instead:

- Defines two minimal `typing.Protocol` types — `ToolsetProtocol` (anything with an async
  `call_tool` method) and `MemoryProtocol` (anything with an async `add_event` method).
- `GovernanceToolset` wraps **any** object that satisfies `ToolsetProtocol`. KAOS
  `AbstractToolset` and pydantic-ai toolsets satisfy that shape directly; LangGraph
  tool nodes, OpenAI tool-calling dispatch, and AWS Bedrock action-group Lambdas
  each need a small adapter that normalizes the framework's tool-call event into
  `(name, args)`.
- Auto-detects KAOS-style `ctx.deps.memory` and `ctx.deps.session_id` for trace
  persistence, and falls back to user-supplied `memory_getter` / `session_id_getter`
  callables when the agent framework exposes those differently.
- Runs standalone for POCs (the included procurement demo uses an in-process mock ERP
  and an in-memory session store — no agent framework involved).

### KAOS is not required for Bedrock

A common confusion: **Bedrock has its own action-group / runtime orchestration and
does not depend on KAOS or SARC.** SARC-KAOS wraps the Bedrock action-group boundary
the same way it wraps a KAOS-style toolset — by sitting inside the Lambda handler
between Bedrock's event and the downstream system. Pick whichever orchestration
fits the deployment; the governance surface is identical.

The same pattern applies in every direction: normalize the framework's tool-call
event → SARC `call_tool(name, args, ctx, tool)` → governed execution → serialize
the result back into the framework's response shape. See
[`docs/integrations.md`](docs/integrations.md) for worked examples and a
side-by-side comparison.

If you are building on KAOS specifically, you wrap your existing toolset and the
SARC layer adds enforcement and audit without changing the agent's tool-call
surface. See [**Connecting to KAOS**](#connecting-to-kaos) below.

---

## Concepts

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

## Quickstart

```bash
git clone https://github.com/besanson/sarc-kaos.git
cd sarc-kaos
pip install -e ".[dev]"

# Run the test suite
pytest

# Run the procurement demo (six scenarios, audit summary at the end)
python examples/procurement_agent/run_demo.py

# Run the KAOS-style adapter demo (mock ctx.deps.memory + ctx.deps.session_id)
python examples/kaos_style_adapter/run_demo.py
```

No external services. No API keys. The procurement demo prints per-scenario outcomes
and a final SARC audit summary; the adapter demo prints the trace records that were
auto-persisted onto the mock `ctx.deps.memory`.

---

## Minimal example: wrap an async toolset

```python
import asyncio
from sarc_kaos import (
    Constraint, ConstraintSpec, GovernanceToolset,
    EscalationRouter, ConstraintViolation,
)

# 1. Any object with async def call_tool(name, args, ctx, tool) is a valid toolset.
class MyToolset:
    async def call_tool(self, name, args, ctx, tool):
        return {"status": "ok", "tool": name, "args": args}

# 2. Declare constraints. Predicates receive a dict — at PAG it has tool+args;
#    at PAA it also has the result.
spec = ConstraintSpec(constraints=[
    Constraint(
        id="ch_high_value_po",
        klass="hard",
        verif="PAG",
        response="block_or_escalate",
        predicate=lambda ctx: (
            ctx["tool"] == "erp.create_po"
            and ctx["args"].get("amount", 0) >= 50_000
        ),
        description="Block purchase orders >= $50,000 before dispatch.",
    ),
])

# 3. Wrap and call.
governed = GovernanceToolset(wrapped=MyToolset(), spec=spec)

async def main():
    try:
        await governed.call_tool("erp.create_po", {"amount": 75_000})
    except ConstraintViolation as exc:
        print(f"blocked at {exc.point.value}: {exc.constraint_id}")

asyncio.run(main())
```

A YAML version of the same spec is loadable via `sarc_kaos.specs.load_spec(path)`;
predicates referenced by name resolve through the built-in registry, and custom ones
can be added with `sarc_kaos.predicates.register`.

---

## POC use cases

The constraint model is general; these are the kinds of tasks the demo and tests
cover and that fit naturally into the PAG/ATM/PAA structure:

- **Procurement approval** — block POs above a threshold (hard/PAG), route first-time
  suppliers for review (escalation/PAG), flag rolling-spend overages (soft/PAA).
  Implemented end-to-end in [`examples/procurement_agent/`](examples/procurement_agent/README.md).
- **Data access** — block queries that select restricted columns (hard/PAG),
  log queries returning > N rows for review (soft/PAA), escalate cross-tenant access
  attempts (escalation/PAG).
- **Customer refunds** — block refunds above an agent's authority (hard/PAG),
  escalate refunds for VIP accounts (escalation/PAG), track cumulative daily refund
  volume per agent (soft/PAA).
- **Incident response / runbooks** — block destructive actions on production hosts
  outside a maintenance window (hard/PAG), escalate any action against a tagged
  "critical" host (escalation/PAG), audit elapsed time on long-running remediations
  (soft/ATM via the `elapsed` field).

In each case the agent code is unchanged; only the `ConstraintSpec` differs.

---

## What works today vs. what is not production-hardened

**Works today**

- Constraint dataclass with class/point compatibility validation (paper §4.2, Table 1).
- `GovernanceToolset.call_tool` dispatching PAG, ATM, PAA enforcement around any
  `ToolsetProtocol`.
- `EscalationRouter` with a pluggable async handler and a default log-only handler.
- `TraceRecord` emission with auto-persistence to `ctx.deps.memory` (KAOS shape) or via
  user-supplied getters.
- YAML / dict spec loading with named-predicate resolution.
- `audit_trace` for offline conformance checking (coverage / placement / response /
  attribution).
- Procurement demo, paper benchmarks, and a test suite.

**Not production-hardened**

- No persistence of constraint specs or trace records beyond the in-process memory
  shim used in the demo. Plug in your own `MemoryProtocol` implementation for durable
  storage.
- No authentication, authorization, or rate-limiting for escalation routing — the
  default handler logs only. Real deployments need a queue, ticketing integration, or
  on-call paging.
- Predicates are arbitrary Python callables, evaluated in-process with no sandbox.
  Treat `ConstraintSpec` content as code, not data, when loading from untrusted
  sources.
- No metrics/tracing exporters. The `TraceRecord.elapsed` field is captured but not
  shipped anywhere by default.
- Concurrency: a single `GovernanceToolset` instance maintains a monotonic action
  counter under no lock. Fine for a single agent loop; partition by instance if you
  need parallel actors.
- No retry, backoff, or idempotency handling around the wrapped toolset call.

---

## Connecting to KAOS

`GovernanceToolset` already speaks the KAOS toolset shape. In a real KAOS app you
wrap your `AbstractToolset` and let the auto-detection of `ctx.deps.memory` and
`ctx.deps.session_id` handle trace persistence:

```python
# In a KAOS / pydantic-ai project (KAOS not vendored here)
from sarc_kaos import GovernanceToolset
from sarc_kaos.specs import load_spec

spec = load_spec("config/sarc_spec.yaml")
governed_tools = GovernanceToolset(wrapped=my_kaos_toolset, spec=spec)

# Hand `governed_tools` to the agent wherever `my_kaos_toolset` would have gone.
# Trace records flow into ctx.deps.memory automatically when the agent runs.
```

A runnable, dependency-free version of this wiring — using a fake KAOS-shaped
`ctx.deps` — lives at [`examples/kaos_style_adapter/`](examples/kaos_style_adapter/README.md).

To go the other direction (use SARC inside an existing KAOS deployment): import
`GovernanceToolset` once at the boundary where your tools are constructed, build a
`ConstraintSpec` from your governance YAML, and replace the toolset reference. No
agent-side code changes are needed.

---

## Repository layout

| Path | Contents |
|---|---|
| [`src/sarc_kaos/`](src/sarc_kaos/) | Core package: constraints, governance, escalation, audit, trace, specs, predicates, CLI |
| [`docs/`](docs/) | Architecture, spec authoring, audit, integrations, production-hardening guides |
| [`examples/procurement_agent/`](examples/procurement_agent/README.md) | End-to-end demo with a mock ERP toolset and YAML spec |
| [`examples/kaos_style_adapter/`](examples/kaos_style_adapter/README.md) | Minimal KAOS/pydantic-ai-shaped `ctx.deps` wiring (no KAOS dependency) |
| [`examples/audit_trace_file/`](examples/audit_trace_file/README.md) | Spec + pass/fail trace JSON for the `sarc-kaos audit` CLI |
| [`examples/human_escalation/`](examples/human_escalation/README.md) | approve / deny / timeout pattern for human-in-the-loop |
| [`examples/langgraph_style_adapter/`](examples/langgraph_style_adapter/README.md) | Wrap a LangGraph-shaped tools node (no `langgraph` dependency) |
| [`examples/openai_tool_calling_adapter/`](examples/openai_tool_calling_adapter/README.md) | Wrap OpenAI-style function dispatch (no `openai` dependency) |
| [`examples/bedrock_action_group_adapter/`](examples/bedrock_action_group_adapter/README.md) | Wrap an AWS Bedrock Agent action-group Lambda handler (no `boto3` dependency) |
| [`benchmarks/`](benchmarks/README.md) | Pre-computed SARC paper evaluation results and the script that produced them |
| [`paper/`](paper/README.md) | LaTeX source for the SARC paper |
| [`tests/`](tests/) | pytest suite covering specs, governance, audit, escalation, predicates, trace, CLI, examples |

---

## Running the test suite

```bash
pytest
```

`pytest-asyncio` is configured in `pyproject.toml` with `asyncio_mode = "auto"`, so
async tests run without per-function decorators.

---

## Benchmarks

Pre-computed results from the SARC paper evaluation live in
[`benchmarks/`](benchmarks/README.md). Regenerate with:

```bash
python benchmarks/sarc_eval.py
```

---

## Paper

The LaTeX source for the SARC paper is in [`paper/`](paper/README.md). The architecture
described there maps 1:1 onto the modules in `src/sarc_kaos/`.

---

## License

MIT — see [`LICENSE`](LICENSE).
