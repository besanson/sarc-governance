# Changelog

All notable changes to `sarc-governance` are documented here.

## [Unreleased]

## [0.2.0] — 2026-05-07

### Added
- **Benchmark callable API** — `benchmarks/sarc_eval.py` now exposes
  `BenchmarkConfig` and `run_benchmark(config, output_dir)` for programmatic
  use from tests and scripts. CLI is backward-compatible.
- **Paper reproduction script** — `python -m benchmarks.reproduce` (or
  `make reproduce`) regenerates all paper artifacts to `artifacts/benchmarks/`
  in one deterministic command.
- **Benchmark smoke test** — `tests/test_benchmark_smoke.py` (11 tests, ~0.05s)
  runs in CI on every PR to catch benchmark harness regressions. Seeds=2,
  n_orders=10 keeps it fast.
- **KAOS example README** — `examples/kaos_pais_adapter/README.md` documents
  all 6 scenarios, `[OK]`/`[BLOCKED]`/`[OK+ESC]` semantics, and how the adapter
  maps SARC onto KAOS/PAIS types.
- **Multi-agent example README** — `examples/multi_agent_governed/README.md`
  explains the two-agent architecture, governance boundaries, and three
  adaptation patterns (customer support, research agent, procurement).
- **Architecture diagrams** — Mermaid `flowchart LR` (runtime architecture),
  `flowchart TD` (decision flow), and `sequenceDiagram` (audit trace lifecycle)
  added to `docs/architecture.md`, `docs/mental-model.md`, and `README.md`.
- **Policy cookbook** — `docs/policy-cookbook.md` with 8 copy-paste YAML recipes:
  cross-tenant access, PII access, procurement thresholds, human escalation,
  tool allowlist/denylist, audit-only mode, refund limits, data export governance.
- **Threat model** — `docs/threat-model.md` documents what SARC protects against,
  trust assumptions, and an example risks/mitigations table.
- **Reproducing results guide** — `docs/reproducing-results.md` for paper readers.
- **SVG logo assets** — `assets/logo/sarc-logo.svg`, `sarc-logo-dark.svg`,
  `sarc-icon.svg`.
- **Makefile** — `install`, `test`, `lint`, `typecheck`, `format`, `demo`,
  `benchmark-smoke`, `reproduce`, `clean` targets.
- `[project.urls]` in `pyproject.toml` — Homepage, Repository, Issues, Changelog.
- PyPI classifiers, `Development Status :: 4 - Beta`.

### Changed
- **CI now checks `examples/` and `benchmarks/`** — `ruff check` and
  `ruff format --check` cover all four directories; format step is now gating.
- **Formatter unified to `ruff-format`** — `black` removed from dev deps and
  pre-commit; `ruff-format` is the single formatter. `[tool.ruff]` replaces
  `[tool.black]` in `pyproject.toml`.
- **Pre-commit updated** — `black` hook removed; `mypy` hook added; now mirrors
  CI exactly.
- `SQLiteTraceStore` — `PRAGMA journal_mode=WAL` enabled for file-backed stores.
- `GovernanceToolset` — `[OK+ESC]` label in KAOS demo distinguishes
  escalated-but-allowed from plain allowed.

### Fixed
- `WebhookEscalationHandler` — replaced blocking `urllib.request.urlopen` with
  `asyncio.to_thread`. Ruff/mypy clean.
- `GovernanceToolset._action_seq` — `asyncio.Lock` added; concurrent `call_tool`
  invocations now produce unique, monotonically increasing action IDs.
- `safe_load_spec` — rejects raw dicts and `extra_predicates` to prevent
  callable injection from untrusted config sources.
- `examples/` — all 13 ruff lint errors fixed; all files pass `ruff format`.
- `examples/audit_trace_file/run_audit.sh` — uses `python -m sarc_governance.cli`
  for portability; falls back to CLI entry point if on PATH.
- `audit.py` mypy errors — `Optional[Constraint]` annotation added, variable
  renamed to avoid `no-redef`.

## [0.1.0] — initial release

- Core SARC governance loop: PAG / ATM / PAA enforcement around any async toolset.
- `ConstraintSpec` with class-to-point compatibility validation.
- `EscalationRouter` with pluggable async handler.
- `audit_trace` for offline conformance checking.
- `policy_checksum`, `inspect_policy`, `diff_policies` for spec lifecycle.
- `MemoryTraceStore`, `JSONLTraceStore`, `SQLiteTraceStore` with optional SHA-256
  hash chain.
- `ExecutionContext` identity bag.
- CLI: `validate`, `audit`, `policy inspect`, `policy diff`, `trace verify-chain`,
  `trace export`, `demo`.
- Procurement demo, pre-production demo, LangGraph / OpenAI / Bedrock adapter
  examples, human escalation example.
- 190 tests.
