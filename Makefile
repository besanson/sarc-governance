.PHONY: install test lint typecheck format demo benchmark-smoke reproduce clean

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

typecheck:
	mypy src/sarc_governance --ignore-missing-imports

format:
	ruff check --fix src tests
	ruff format src tests

demo:
	python examples/kaos_pais_adapter/run_demo.py

benchmark-smoke:
	pytest -q tests/test_benchmark_smoke.py

reproduce:
	python -m benchmarks.reproduce

clean:
	rm -rf artifacts .pytest_cache .mypy_cache .ruff_cache __pycache__
