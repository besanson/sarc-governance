# Contributing to sarc-governance

## Getting started

```bash
git clone https://github.com/besanson/sarc-governance.git
cd sarc-governance
pip install -e ".[dev]"
pytest
```

## Running the full check locally

```bash
make quality          # lint + format-check + typecheck + test in one command
# or individually:
pytest --tb=short -q
ruff check src tests examples benchmarks
ruff format --check src tests examples benchmarks
mypy src/sarc_governance --ignore-missing-imports
```

## What to work on

- Bug reports and fixes — open an issue first for anything non-trivial
- New built-in predicates in `src/sarc_governance/predicates.py`
- New escalation handlers in `src/sarc_governance/handlers.py`
- New adapter examples in `examples/`
- Documentation improvements in `docs/`

See [docs/production-hardening.md](docs/production-hardening.md) for the known
gaps that are explicitly out of scope for the core library.

## Pull request checklist

- [ ] `pytest` passes with no new failures
- [ ] New behaviour is covered by tests
- [ ] Public API additions are exported from `src/sarc_governance/__init__.py`
- [ ] No new mandatory dependencies (keep the core stdlib + pyyaml only)

## Code style

`ruff format` with `line-length = 99`. Run `make format` before opening a PR. Linting uses `ruff check`; type checking uses `mypy`. Both are gated in CI and pre-commit.

## Commit messages

Follow the existing pattern: `type(scope): short description` where type is one of
`feat`, `fix`, `docs`, `chore`, `test`, `refactor`.
