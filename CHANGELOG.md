# Changelog

All notable changes to `sarc-governance` are documented here.

## [Unreleased]

### Added
- `WebhookEscalationHandler` — delivers escalation events as JSON POST to any
  HTTP/HTTPS endpoint (Slack, internal sidecars, API gateways). Uses
  `asyncio.to_thread` to avoid blocking the event loop. Exported from the
  top-level package.
- `safe_load_spec` — production spec loading path that accepts only file paths
  and no `extra_predicates`, preventing callable injection from untrusted config.
  Exported from the top-level package.
- `examples/kaos_pais_adapter/` — adapter for [KAOS](https://github.com/axsaucedo/kaos):
  `build_governed_toolset` wraps `DelegationToolset` with zero adapter code;
  PAIS session memory auto-detected as the trace backend.
- `examples/multi_agent_governed/` — end-to-end two-agent chain (coordinator +
  validator) with independent `ConstraintSpec`s and five scenarios with assertions.
- `docs/trace-stores.md` — Postgres (psycopg2) and Redis Streams adapter skeletons
  for multi-writer deployments.
- `docs/security-model.md` — `safe_load_spec` guidance and threat model.
- `docs/integrations.md` — KAOS PAIS section with four-line integration recipe.
- GitHub Actions CI workflow (Python 3.11 and 3.12).
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- `requirements-dev.txt` for restricted-network environments.

### Fixed
- `GovernanceToolset._action_seq` — added `asyncio.Lock` so concurrent
  `call_tool` invocations produce unique, monotonically increasing action IDs.
- `WebhookEscalationHandler` — replaced blocking `urllib.request.urlopen` with
  `asyncio.to_thread` to avoid blocking the event loop.
- `examples/kaos_pais_adapter/run_demo.py` — fixed import to work from a fresh
  checkout without `PYTHONPATH` manipulation.
- `pyproject.toml` — lowered `setuptools>=68` to `>=61` to avoid unnecessary
  PyPI fetches in restricted environments.

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
