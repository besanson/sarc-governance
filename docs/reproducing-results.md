# Reproducing Results

This document explains how to reproduce all benchmark outputs reported in the paper, verify their integrity, and interpret what the numbers do and do not represent.

## One-command reproduction

```bash
make reproduce
```

This runs `python -m benchmarks.reproduce` with default parameters (50 seeds, 1000 orders per seed) and writes all output files to `artifacts/benchmarks/`.

## Generated files

| File | Description |
|------|-------------|
| `artifacts/benchmarks/sarc_eval_results.csv` | Regime comparison table. 5 regimes × 50 seeds = **250 rows**. Each row records allow/block/escalation counts and synthetic latency for one (regime, seed) pair. |
| `artifacts/benchmarks/sarc_eval_noise_sweep.csv` | Predicate-noise / enforcement-failure sweep. 4 noise levels × 3 failure rates × 50 seeds = **600 rows**. Used to characterise robustness under degraded conditions. |
| `artifacts/benchmarks/sarc_eval_summary.json` | Per-regime means and 95% confidence intervals aggregated across all seeds. Primary source for in-text statistics and paper figures. |

## Determinism

The benchmark uses a fixed random seed sequence derived from the `--seeds` count. Running the same command twice on the same machine produces **byte-identical output files**. The seed sequence is not platform-dependent; results should also be identical across operating systems.

## What the numbers do NOT represent

- **Wall-clock timing is synthetic.** The `latency_ms_per_step` column is a fixed overhead value assigned per regime in the simulation configuration. It is not measured from real tool calls or network latency. Do not use it to compare deployment performance.
- **This is a controlled simulation, not a deployment benchmark.** The five governance regimes are exercised against a synthetic order workload. Results reflect the logical behaviour of each regime under the simulated workload, not the performance of any live system.

## Mapping outputs to the paper

| Paper location | Source file |
|----------------|-------------|
| Table 2 (per-regime allow/block/escalation rates) | `sarc_eval_results.csv` |
| Noise and failure sweep (Section 4.3) | `sarc_eval_noise_sweep.csv` |
| Confidence intervals quoted in text | `sarc_eval_summary.json` |

## Fast smoke test

To verify the pipeline runs end-to-end without waiting for the full 250-run suite:

```bash
make benchmark-smoke
```

This runs `pytest tests/test_benchmark_smoke.py` with `seeds=2` and `n_orders=10`. The smoke test checks output structure and basic statistical invariants but does not reproduce paper numbers.

## Running with custom parameters

```bash
python -m benchmarks.reproduce --seeds 10 --n-orders 1000 --output-dir /tmp/sarc_out
```

| Flag | Default | Description |
|------|---------|-------------|
| `--seeds N` | 50 | Number of random seeds to run per regime. |
| `--n-orders N` | 1000 | Number of orders generated per seed (matches the paper). |
| `--output-dir PATH` | `artifacts/benchmarks` | Directory for output files. Created if it does not exist. |

Results produced with non-default seed counts will differ numerically from the paper but will have the same file structure and column schema.

## Checking output structure

A correctly generated `sarc_eval_summary.json` has the following top-level structure:

```json
{
  "n_cases": 250,
  "n_runs": 50,
  "seed": 50,
  "benchmark": {
    "<regime_name>": {
      "allow_count":      { "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0 },
      "block_count":      { "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0 },
      "escalation_count": { "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0 }
    }
  },
  "noise_sweep": {
    "<noise_level>": {
      "<failure_rate>": {
        "allow_count":      { "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0 },
        "block_count":      { "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0 },
        "escalation_count": { "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0 }
      }
    }
  }
}
```

Keys present in every regime entry: `allow_count`, `block_count`, `escalation_count`. Each value is an object with `mean`, `ci95_low`, and `ci95_high`.

## Common questions

**Q: Why do the timings differ from my machine?**

`latency_ms_per_step` is a fixed synthetic overhead assigned to each regime in the simulation configuration — it is not measured wall time. The value is the same on every machine and every run. If you need to measure real execution latency, instrument the runner directly.

**Q: Can I reproduce with fewer seeds?**

Yes. Pass `--seeds N` for any positive integer N. The output files will be structurally identical to the paper outputs, but the means and confidence intervals will differ because they are computed over fewer samples. Use a reduced seed count for development and the full 50-seed run to match the paper exactly.

**Q: How do I verify the output has not been tampered with?**

Re-run the full reproduction and diff the CSVs against the committed artifacts:

```bash
make reproduce
diff artifacts/benchmarks/sarc_eval_results.csv <previously-saved-copy>
diff artifacts/benchmarks/sarc_eval_noise_sweep.csv <previously-saved-copy>
```

For the same `--seeds` count and `--n-orders` count, the files are byte-identical, so any diff indicates either a code change or tampering.
