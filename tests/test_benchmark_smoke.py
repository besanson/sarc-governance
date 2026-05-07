"""Benchmark harness smoke test.

Verifies that run_benchmark() executes, produces the expected output files,
and returns a structurally valid summary dict. Uses a minimal config (2 seeds,
10 orders) to keep the test fast (< 1 second).

Does NOT check absolute performance numbers, which vary across machines and
CI environments.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys

import pytest

# Allow import from repo root when running without editable install.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.sarc_eval import BenchmarkConfig, run_benchmark  # noqa: E402

# Smoke config: 2 seeds × 5 regimes = 10 benchmark rows; 2 × 4 × 3 = 24 noise rows.
_SMOKE = BenchmarkConfig(seeds=2, n_orders=10, noise_sweep=True)
_N_REGIMES = 5
_NOISE_COMBOS = 4 * 3  # 4 pred_noise × 3 exec_fail levels


@pytest.fixture(scope="module")
def benchmark_result(tmp_path_factory):
    out = tmp_path_factory.mktemp("benchmark_smoke")
    return run_benchmark(_SMOKE, output_dir=out), out


def test_summary_json_exists(benchmark_result):
    result, out = benchmark_result
    assert pathlib.Path(result["summary_json"]).exists()


def test_benchmark_csv_exists(benchmark_result):
    result, out = benchmark_result
    assert pathlib.Path(result["benchmark_csv"]).exists()


def test_noise_csv_exists(benchmark_result):
    result, out = benchmark_result
    assert result["noise_csv"] is not None
    assert pathlib.Path(result["noise_csv"]).exists()


def test_summary_has_required_keys(benchmark_result):
    result, out = benchmark_result
    required = {"n_cases", "n_runs", "seed", "allow_count", "block_count", "escalation_count"}
    assert required <= result.keys(), f"Missing keys: {required - result.keys()}"


def test_summary_json_is_valid(benchmark_result):
    result, _ = benchmark_result
    with open(result["summary_json"]) as f:
        data = json.load(f)
    assert "benchmark" in data
    assert "noise_sweep" in data
    assert isinstance(data["benchmark"], list)
    assert len(data["benchmark"]) > 0


def test_benchmark_csv_row_count(benchmark_result):
    result, _ = benchmark_result
    with open(result["benchmark_csv"], newline="") as f:
        rows = list(csv.DictReader(f))
    expected = _SMOKE.seeds * _N_REGIMES
    assert len(rows) == expected, f"Expected {expected} rows, got {len(rows)}"


def test_noise_csv_row_count(benchmark_result):
    result, _ = benchmark_result
    with open(result["noise_csv"], newline="") as f:
        rows = list(csv.DictReader(f))
    expected = _SMOKE.seeds * _NOISE_COMBOS
    assert len(rows) == expected, f"Expected {expected} rows, got {len(rows)}"


def test_n_cases_matches_benchmark_csv(benchmark_result):
    result, _ = benchmark_result
    with open(result["benchmark_csv"], newline="") as f:
        rows = list(csv.DictReader(f))
    assert result["n_cases"] == len(rows)


def test_n_runs_matches_config(benchmark_result):
    result, _ = benchmark_result
    assert result["n_runs"] == _SMOKE.seeds


def test_output_files_written_to_tmp(benchmark_result):
    """Verify the test writes only to tmp_path, not the repo tree."""
    result, out = benchmark_result
    for key in ("benchmark_csv", "noise_csv", "summary_json"):
        if result[key]:
            p = pathlib.Path(result[key])
            assert p.is_relative_to(out), f"{key} written outside tmp_path: {p}"


def test_sarc_regime_zero_hard_violations_clean_config(benchmark_result):
    """Under zero pred_noise and zero exec_fail, SARC should have 0 hard violations."""
    result, _ = benchmark_result
    # block_count reflects hard_executed across all SARC episodes;
    # with clean predicates and no exec_fail this should be 0.
    assert result["block_count"] == 0, (
        f"Expected 0 hard violations under clean SARC config, got {result['block_count']}"
    )
