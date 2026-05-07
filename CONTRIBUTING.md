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
pytest --tb=short -q      # 206 tests, should all pass
ruff check src tests      # linting
mypy src/sarc_governance --ignore-missing-imports  # type checking
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

`black` with `line-length = 99` and `target-version = py311`. Run `black src tests`
before opening a PR.

## Commit messages

Follow the existing pattern: `type(scope): short description` where type is one of
`feat`, `fix`, `docs`, `chore`, `test`, `refactor`.
