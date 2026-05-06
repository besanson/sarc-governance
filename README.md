# sarc-governance

A runtime governance layer that wraps any async toolset and enforces declarative
constraints (hard / soft / escalation) at three in-process points around every tool call.

> **Status:** developer toolkit + pre-production foundations on top of the SARC
> architecture from *"SARC: A Runtime Governance Architecture for Tool-Using
> Agentic AI Systems"* ([`paper/`](paper/README.md)). Suitable for prototypes,
> evaluation, serious POCs, and as the runtime spine of a hardened deployment;
> see [docs/pre-production-checklist.md](docs/pre-production-checklist.md) for
> what now ships in the library, and
> [docs/production-hardening.md](docs/production-hardening.md) for what is still
> the deploying organisation's responsibility.

## Documentation

- [Architecture](docs/architecture.md) — SARC loop, components, class × point compatibility.
- [Spec authoring](docs/spec-authoring.md) — YAML schema, predicates, common mistakes.
- [Audit traces](docs/audit-traces.md) — trace shapes, `audit_trace` semantics, CI workflow.
- [Integrations](docs/integrations.md) — LangGraph-style, OpenAI tool calling, AWS Bedrock action groups, generic async toolsets.
- [Pre-production checklist](docs/pre-production-checklist.md) — what now ships vs. what you still wire up.
- [Policy lifecycle](docs/policy-lifecycle.md) — `PolicyMetadata`, checksum, diff, CI gating.
- [Trace stores](docs/trace-stores.md) — Memory / JSONL / SQLite backends and the hash chain.
- [Security model](docs/security-model.md) — threat model, what is and isn't protected.
- [Failure modes](docs/failure-modes.md) — what happens on memory / escalation / spec errors.
- [Production hardening](docs/production-hardening.md) — persistence, observability, auth, perf, CI/CD.

## Command-line interface

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
[docs/audit-traces.md](docs/audit-traces.md) for the trace schema and
[docs/policy-lifecycle.md](docs/policy-lifecycle.md) for the policy commands.

---

## Framework-agnostic by design

**`sarc-governance` does not import any specific agent framework.** LangGraph, OpenAI,
boto3 / Bedrock, pydantic-ai, and similar libraries are all optional — none are
required to be installed. The package is framework-neutral and depends only on
`pyyaml` plus the standard library. SARC Governance is the *governance layer*;
orchestration is whatever you already use.

What it does instead:

- Defines two minimal `typing.Protocol` types — `ToolsetProtocol` (anything with an async
  `call_tool` method) and `MemoryProtocol` (anything with an async `add_event` method).
- `GovernanceToolset` wraps **any** object that satisfies `ToolsetProtocol`. LangGraph
  tool nodes, OpenAI tool-calling dispatch, AWS Bedrock action-group Lambdas, and
  arbitrary in-house async toolsets each need (at most) a small adapter that
  normalizes the framework's tool-call event into `(name, args)`.
- Auto-detects `ctx.deps.memory` and `ctx.deps.session_id` for trace persistence
  when the orchestration layer exposes that shape, and falls back to user-supplied
  `memory_getter` / `session_id_getter` callables when the agent framework exposes
  those differently.
- Runs standalone for POCs (the included procurement demo uses an in-process mock ERP
  and an in-memory session store — no agent framework involved).

The recipe is the same in every direction: normalize the framework's tool-call
event → SARC `call_tool(name, args, ctx, tool)` → governed execution → serialize
the result back into the framework's response shape. See
[`docs/integrations.md`](docs/integrations.md) for worked examples and a
side-by-side comparison.

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
git clone https://github.com/besanson/sarc-governance.git
cd sarc-governance
pip install -e ".[dev]"

# Run the test suite
pytest

# Run the procurement demo (six scenarios, audit summary at the end)
python examples/procurement_agent/run_demo.py
```

No external services. No API keys. The procurement demo prints per-scenario outcomes
and a final SARC audit summary.

---

## Minimal example: wrap an async toolset

```python
import asyncio
from sarc_governance import (
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

A YAML version of the same spec is loadable via `sarc_governance.specs.load_spec(path)`;
predicates referenced by name resolve through the built-in registry, and custom ones
can be added with `sarc_governance.predicates.register`.

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

## Pre-production foundations

On top of the core enforcement loop, the library now ships the
foundations a deploying organisation typically needs before promoting a
SARC-governed agent to a critical path:

| Piece | Module | What it gives you |
|---|---|---|
| `ExecutionContext` | [`context.py`](src/sarc_governance/context.py) | Typed identity bag (principal / agent / tenant / session / roles / environment / request id). Auto-stamped onto every trace record when supplied. |
| Policy lifecycle | [`policy.py`](src/sarc_governance/policy.py) | `PolicyMetadata`, `policy_checksum`, `inspect_policy`, `diff_policies`. Content fingerprint + structured diff for CI gating. |
| Trace stores | [`stores/`](src/sarc_governance/stores) | `MemoryTraceStore`, `JSONLTraceStore`, `SQLiteTraceStore` — three durable backends behind a shared `TraceStore` protocol. |
| Hash chain | [`hashchain.py`](src/sarc_governance/hashchain.py) | SHA-256 chain over canonical JSON of each record. Detects tampering, removal, reordering. *Tamper-evident, not tamper-proof.* |
| Failure-mode safety | tests in [`tests/test_failure_modes.py`](tests/test_failure_modes.py) | Memory backend / escalation handler exceptions are caught and logged; a failing escalation **never** turns a hard block into a pass. |

Try them end-to-end with the included example:

```bash
python examples/preproduction_trace_store/run_demo.py
```

CI gate one-liners:

```bash
sarc-governance policy inspect config/spec.yaml --json
sarc-governance policy diff old_spec.yaml new_spec.yaml --exit-code
sarc-governance trace verify-chain trace.jsonl
sarc-governance trace export trace.sqlite trace.jsonl
```

See [docs/pre-production-checklist.md](docs/pre-production-checklist.md)
for the full status mapping.

---

## What works today vs. what is not production-hardened

**Works today**

- Constraint dataclass with class/point compatibility validation (paper §4.2, Table 1).
- `GovernanceToolset.call_tool` dispatching PAG, ATM, PAA enforcement around any
  `ToolsetProtocol`.
- `EscalationRouter` with a pluggable async handler and a default log-only handler.
- `TraceRecord` emission with auto-persistence to a `ctx.deps.memory` shape or via
  user-supplied getters; optional auto-stamp of an `ExecutionContext`.
- YAML / dict spec loading with named-predicate resolution.
- `audit_trace` for offline conformance checking (coverage / placement / response /
  attribution).
- `policy_checksum`, `inspect_policy`, `diff_policies` for spec lifecycle gating.
- `MemoryTraceStore`, `JSONLTraceStore`, `SQLiteTraceStore` with optional
  tamper-evident SHA-256 hash chain and `verify_chain` CLI.
- Procurement demo, pre-production demo, paper benchmarks, and a test suite (>180 tests).

**Still the deploying organisation's job**

- Multi-writer durable storage at scale — the shipped stores are single-writer
  (file or single-file SQLite). Bring a real backend if you need multi-process
  durability.
- Authentication, authorization, and rate-limiting for escalation routing — the
  default handler logs only. Real deployments need a queue, ticketing integration,
  or on-call paging.
- Predicate sandboxing. Predicates are arbitrary Python callables evaluated
  in-process. Treat `ConstraintSpec` content as code, not data, when loading from
  untrusted sources.
- Metrics / tracing exporters. The library does not depend on OpenTelemetry; an
  OTel adapter against the trace store protocol is straightforward to write.
- Concurrency across actors: a single `GovernanceToolset` instance maintains a
  monotonic action counter under no lock. Fine for a single agent loop; partition
  by instance if you need parallel actors.
- Spec approval enforcement. `PolicyMetadata.approval_status` is a string — your
  CI/CD enforces what `approved` means.
- Retry / backoff / idempotency around the wrapped toolset call.

---

## Repository layout

| Path | Contents |
|---|---|
| [`src/sarc_governance/`](src/sarc_governance/) | Core package: constraints, governance, escalation, audit, trace, specs, predicates, CLI, context, policy, hashchain, stores |
| [`docs/`](docs/) | Architecture, spec authoring, audit, integrations, pre-production checklist, policy lifecycle, trace stores, security model, failure modes, production-hardening |
| [`examples/procurement_agent/`](examples/procurement_agent/README.md) | End-to-end demo with a mock ERP toolset and YAML spec |
| [`examples/audit_trace_file/`](examples/audit_trace_file/README.md) | Spec + pass/fail trace JSON for the `sarc-governance audit` CLI |
| [`examples/preproduction_trace_store/`](examples/preproduction_trace_store/README.md) | SQLite trace store + hash chain + policy diff demo |
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
described there maps 1:1 onto the modules in `src/sarc_governance/`.

---

## License

MIT — see [`LICENSE`](LICENSE).
