LINT_PATHS = src tests examples benchmarks

.PHONY: install test lint format-check format typecheck demo benchmark-smoke reproduce quality clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	ruff check $(LINT_PATHS)

format-check:
	ruff format --check $(LINT_PATHS)

format:
	ruff check --fix $(LINT_PATHS)
	ruff format $(LINT_PATHS)

typecheck:
	mypy src/sarc_governance --ignore-missing-imports

quality: lint format-check typecheck test

demo:
	python examples/kaos_pais_adapter/run_demo.py

benchmark-smoke:
	python -m pytest -q tests/test_benchmark_smoke.py

reproduce:
	python -m benchmarks.reproduce

clean:
	rm -rf artifacts dist build .pytest_cache .mypy_cache .ruff_cache __pycache__
