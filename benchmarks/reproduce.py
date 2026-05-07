"""Reproduce the SARC paper benchmark artifacts.

Usage::

    python -m benchmarks.reproduce [--output-dir artifacts/benchmarks] [--seeds 50]

Outputs:

    artifacts/benchmarks/
        sarc_eval_results.csv     regime comparison (paper Table 2)
        sarc_eval_noise_sweep.csv  predicate-noise / enforcement-failure sweep
        sarc_eval_summary.json    per-regime means and 95% CI

The script uses a fixed seed sequence and is fully deterministic.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

# Allow running as `python -m benchmarks.reproduce` from the repo root.
_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.sarc_eval import BenchmarkConfig, run_benchmark  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce SARC paper benchmark artifacts")
    parser.add_argument(
        "--output-dir",
        default="artifacts/benchmarks",
        help="Directory to write output files (default: artifacts/benchmarks)",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=50,
        help="Number of random seeds (default: 50, matches paper)",
    )
    parser.add_argument(
        "--n-orders",
        type=int,
        default=1000,
        dest="n_orders",
        help="Purchase orders per episode (default: 1000, matches paper)",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)
    config = BenchmarkConfig(seeds=args.seeds, n_orders=args.n_orders, noise_sweep=True)

    print("Reproducing SARC benchmark artifacts")
    print(f"  seeds    : {config.seeds}")
    print(f"  n_orders : {config.n_orders}")
    print(f"  output   : {output_dir.resolve()}")
    print()

    t0 = time.perf_counter()
    result = run_benchmark(config, output_dir)
    elapsed = time.perf_counter() - t0

    print(f"Done in {elapsed:.1f}s")
    print()
    print(f"Benchmark CSV  : {result['benchmark_csv']}")
    print(f"Noise sweep CSV: {result['noise_csv']}")
    print(f"Summary JSON   : {result['summary_json']}")
    print()
    print(f"  Total rows (benchmark): {result['n_cases']}")
    noise_rows = result.get("noise_sweep", [])
    print(f"  Total rows (noise sweep): {len(noise_rows) * config.seeds if noise_rows else 'n/a'}")
    print(f"  Seed range: 0..{config.seeds - 1}")
    print(f"  SARC hard violations: {result['block_count']}")
    print(f"  SARC escalations    : {result['escalation_count']}")


if __name__ == "__main__":
    main()
