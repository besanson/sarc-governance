# sarc-governance

![CI](https://github.com/besanson/sarc-governance/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue)](http://mypy-lang.org/)

A runtime governance layer that wraps any async toolset and enforces declarative
constraints (hard / soft / escalation) at three in-process points around every tool call.

> **Status — read this first.** Developer toolkit + pre-production
> foundations on top of the SARC architecture from *"SARC: A Runtime
> Governance Architecture for Tool-Using Agentic AI Systems"*
> ([`paper/`](paper/README.md)). Stable enough for prototypes,
> evaluation, serious POCs, and as the runtime spine of a hardened
> deployment. **It is not a turnkey production system.** The hash chain
> is *tamper-evident, not tamper-proof*; `approval_status="approved"` is
> a string that the deploying organisation's CI/CD must enforce; the
> shipped trace stores are single-writer; the default escalation router
> only logs. See [docs/mental-model.md](docs/mental-model.md) for the
> full "is / is not" map and
> [docs/production-hardening.md](docs/production-hardening.md) for what
> remains your responsibility.

## Start here

- [Mental model](docs/mental-model.md) — what `sarc-governance` is and is not, in one page.
- [Quickstart for developers](docs/quickstart-for-developers.md) — 10-minute path from clone to first governed call.
- [FAQ](docs/faq.md) — does it call cloud providers, replace Bedrock, make logs tamper-proof, etc.
- [Integration checklist](docs/integration-checklist.md) — the decisions you have to make before shipping.
- [Policy cookbook](docs/policy-cookbook.md) — copy-paste YAML recipes for common governance patterns.

## Reference docs

- [Architecture](docs/architecture.md) — SARC loop, components, class × point compatibility.
- [Spec authoring](docs/spec-authoring.md) — YAML schema, predicates, common mistakes.
- [Audit traces](docs/audit-traces.md) — trace shapes, `audit_trace` semantics, CI workflow.
- [Integrations](docs/integrations.md) — KAOS PAIS, LangGraph-style, OpenAI tool calling, AWS Bedrock action groups, generic async toolsets.
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

**`sarc-governance` does not import any specific agent framework.** KAOS, LangGraph,
OpenAI, boto3 / Bedrock, pydantic-ai, and similar libraries are all optional — none
are required to be installed. The package is framework-neutral and depends only on
`pyyaml` plus the standard library. SARC Governance is the *governance layer*;
orchestration is whatever you already use.

What it does instead:

- Defines two minimal `typing.Protocol` types — `ToolsetProtocol` (anything with an async
  `call_tool` method) and `MemoryProtocol` (anything with an async `add_event` method).
- `GovernanceToolset` wraps **any** object that satisfies `ToolsetProtocol`. KAOS's
  `DelegationToolset`, LangGraph tool nodes, OpenAI tool-calling dispatch, AWS Bedrock
  action-group Lambdas, and arbitrary in-house async toolsets each need (at most) a
  small adapter that normalizes the framework's tool-call event into `(name, args)`.
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

## How SARC relates to other approaches

| Approach | What it does well | Gap SARC addresses |
|---|---|---|
| Plain logging | Records events after they happen | Does not enforce before tool execution |
| Tool allowlists | Restricts available tools | Usually lacks contextual policy decisions |
| LLM output guardrails | Filters model inputs/outputs | May not govern concrete tool-call arguments |
| Framework callbacks | Hooks into agent execution | Often framework-specific; not audit-centric |
| General policy engines (OPA, Cedar) | Express rich policies | May not provide agent/tool trace semantics |
| SARC | Runtime action governance + typed audit traces | Early-stage developer toolkit; not production-hardened |

SARC complements rather than replaces these controls. Logging is still useful. IAM still owns authentication. Model-level guardrails still filter outputs. SARC adds the enforcement loop and the audit trail at the tool-dispatch boundary.

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

**Restricted network / corporate proxy?** If your environment blocks PyPI during
the build step, use the fallback path:

```bash
pip install -r requirements-dev.txt          # install dev deps via your mirror/cache
pip install -e . --no-build-isolation        # install package without re-fetching build tools
pytest
```

**No pip access at all?** If you cannot run pip in any form, skip the install entirely:

```bash
PYTHONPATH=src pytest
```

This requires `pytest` and `pytest-asyncio` to already be present in your Python
environment. If `pytest-asyncio` is missing the async tests will error — install it
first (`pip install pytest-asyncio>=0.23`) or your test run will be incomplete.

No external services. No API keys. The procurement demo prints per-scenario outcomes
and a final SARC audit summary.

---

## Choose your path

### I am reading the paper

Start with the [mental model](docs/mental-model.md), then regenerate the benchmark artifacts:

```bash
make reproduce
```

Outputs are written to `artifacts/benchmarks/`. The benchmark script is `benchmarks/sarc_eval.py`; the paper maps directly to the architecture in `src/sarc_governance/`.

### I want to run a demo

```bash
python examples/kaos_pais_adapter/run_demo.py    # KAOS/PAIS integration with 6 governance scenarios
python examples/multi_agent_governed/run_demo.py # Two chained agents with independent specs
python examples/procurement_agent/run_demo.py    # Procurement approval with YAML spec
```

### I want to govern my own agent

Read the [integration quickstart](docs/quickstart-for-developers.md), then pick a recipe from the [policy cookbook](docs/policy-cookbook.md).

### I want to inspect audit traces

```bash
sarc-governance audit examples/audit_trace_file/spec.yaml examples/audit_trace_file/trace_fail.json
```

See [docs/audit-traces.md](docs/audit-traces.md) for the trace schema.

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

## Limitations

SARC is a developer toolkit and research artifact. Before deploying in a regulated or high-stakes environment, read these limitations:

- **Not a replacement for IAM.** SARC does not authenticate callers or authorize access. It enforces constraints on tool-call arguments.
- **Not a replacement for secure sandboxing.** Predicates are arbitrary Python callables evaluated in-process. A malicious spec is malicious code.
- **Not a complete prompt-injection defense.** SARC does not parse model outputs. Prompt injection that changes tool arguments can still trigger a constraint; prompt injection that injects a new tool call is governed only if that tool call reaches GovernanceToolset.
- **Not a distributed transaction system.** The shipped trace stores are single-writer. Multi-agent scenarios with shared state require application-level coordination.
- **Trace integrity depends on deployment choices.** The hash chain is tamper-evident, not tamper-proof. verify-chain detects tampering after the fact; it is not a real-time integrity monitor.
- **Policy correctness depends on policy authors.** A predicate that always returns False is a silent governance gap. Test your predicates.

See [docs/threat-model.md](docs/threat-model.md) for the full threat model.

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
| [`examples/multi_agent_governed/`](examples/multi_agent_governed/run_demo.py) | Two governed agents chained — coordinator + validator with independent specs; shows constraint propagation across an agent boundary |
| [`examples/kaos_pais_adapter/`](examples/kaos_pais_adapter/adapter.py) | Adapter for [KAOS](https://github.com/axsaucedo/kaos) — wraps `DelegationToolset`, wires PAIS session memory as the trace store (no `pais` dependency to run the example) |
| [`examples/langgraph_style_adapter/`](examples/langgraph_style_adapter/README.md) | Wrap a LangGraph-shaped tools node (no `langgraph` dependency) |
| [`examples/openai_tool_calling_adapter/`](examples/openai_tool_calling_adapter/README.md) | Wrap OpenAI-style function dispatch (no `openai` dependency) |
| [`examples/bedrock_action_group_adapter/`](examples/bedrock_action_group_adapter/README.md) | Wrap an AWS Bedrock Agent action-group Lambda handler (no `boto3` dependency) |
| [`benchmarks/`](benchmarks/README.md) | Pre-computed SARC paper evaluation results and the script that produced them |
| [`paper/`](paper/README.md) | LaTeX source for the SARC paper |
| [`tests/`](tests/) | pytest suite covering specs, governance, audit, escalation, predicates, trace, CLI, examples |

---

## Running the test suite

```bash
pytest                   # standard — requires pip install -e ".[dev]"
PYTHONPATH=src pytest    # no-install fallback — requires pytest and pytest-asyncio in your environment
```

`pytest-asyncio` is configured in `pyproject.toml` with `asyncio_mode = "auto"`, so
async tests run without per-function decorators. **`pytest-asyncio` is required** — without
it the async tests will error, not skip, and your run will be incomplete.

---

## Benchmarks

Pre-computed results from the SARC paper evaluation live in
[`benchmarks/`](benchmarks/README.md). Regenerate with:

```bash
python benchmarks/sarc_eval.py
```

---

## Reproducing benchmark results

To regenerate the benchmark artifacts from the paper:

```bash
pip install -e ".[dev]"
make reproduce
```

Outputs are written to `artifacts/benchmarks/`:
- `sarc_eval_results.csv` — regime comparison across 50 seeds
- `sarc_eval_noise_sweep.csv` — predicate-noise / enforcement-failure sweep
- `sarc_eval_summary.json` — per-regime means and 95% confidence intervals

The reproduction uses a fixed random seed sequence and is deterministic. CI runs a fast smoke test (`make benchmark-smoke`) on every PR to verify the benchmark harness is not broken.

---

## Paper

The LaTeX source for the SARC paper is in [`paper/`](paper/README.md). The architecture
described there maps 1:1 onto the modules in `src/sarc_governance/`.

---

## License

MIT — see [`LICENSE`](LICENSE).
