# SARC Benchmarks

This directory contains the evaluation artifacts from the SARC paper.

## Files

| File | Description |
|---|---|
| `sarc_eval.py` | Simulation driver: runs five governance regimes over synthetic procurement episodes |
| `sarc_benchmark.csv` | Pre-computed results for 50 seeds × 5 regimes = 250 episodes |
| `sarc_noise_sweep.csv` | Noise sweep: 50 seeds × 4 pred_noise levels × 3 exec_fail levels |
| `sarc_eval_summary.json` | Aggregated means and 95% CIs for all metrics and regimes |

## How to regenerate

```bash
python benchmarks/sarc_eval.py \
  --benchmark benchmarks/sarc_benchmark.csv \
  --noise benchmarks/sarc_noise_sweep.csv \
  --summary benchmarks/sarc_eval_summary.json
```

The script has **no external dependencies** — only the standard library.

## Regimes compared

| Regime | Description |
|---|---|
| `post_hoc` | No pre-dispatch governance; audit only after the fact |
| `output_filter` | Text-level output filter (25% miss rate on side-effectful actions) |
| `workflow_rules` | Static workflow rules; catches only registered hard PO pattern |
| `policy_as_code_only` | Generic policy layer; catches hard + escalation but no soft window |
| `sarc` | Full SARC (PAG + PAA); zero hard-executed, 90% soft-overage reduction |

## Key results (50-seed means)

| Metric | post_hoc | sarc |
|---|---|---|
| `hard_executed` | 26.8 | 0.0 |
| `soft_overages` | 949.8 | 98.8 |
| `supplier_without_review` | 132.3 | 0.0 |
| `latency_ms_per_step` | 0.0 | 21.0 |

## Relation to the paper

These results correspond to **Table 2** and **Figure 3** in the SARC paper
(see [`../paper/`](../paper/README.md)).  The simulation models 1 000 synthetic
purchase order events per episode drawn from a log-normal amount distribution
(μ = 8.5, σ = 1.2 on log scale).

The `sarc_eval.py` script encodes the same constraint logic as the
`sarc_governance` package but as a self-contained simulation.  The production
package (`src/sarc_governance/`) is the generalisable version that wraps real
toolsets.
