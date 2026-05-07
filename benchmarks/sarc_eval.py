"""SARC paper evaluation benchmark.

Callable API (used by tests and the reproduce script)::

    from benchmarks.sarc_eval import BenchmarkConfig, run_benchmark

    result = run_benchmark(BenchmarkConfig(seeds=2, n_orders=10), output_dir=Path("/tmp/out"))
    # result is a dict with n_cases, n_runs, seed, allow_count, block_count, escalation_count, ...

CLI::

    python benchmarks/sarc_eval.py [--benchmark FILE] [--noise FILE] [--summary FILE]
                                    [--seeds N] [--n-orders N]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import random
from dataclasses import dataclass, field
from statistics import mean, stdev
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Constraint spec (paper evaluation — independent of sarc_governance package)
# ---------------------------------------------------------------------------


@dataclass
class Constraint:
    cid: str
    klass: str
    predicate: str
    verif: str
    resp: str


SPEC: Dict[str, Any] = {
    "constraints": [
        {
            "id": "ch_high_value_po",
            "class": "hard",
            "predicate": "tool == 'erp.create_po' and amount >= 50000",
            "verif": "PAG",
            "resp": "block_or_escalate",
        },
        {
            "id": "ce_first_time_supplier",
            "class": "escalation",
            "predicate": "first_time_supplier is True",
            "verif": "PAG",
            "resp": "suspend_route_default_deny",
        },
        {
            "id": "cs_rolling_spend",
            "class": "soft",
            "predicate": "rolling_24h_spend >= 475000",
            "verif": "PAA",
            "resp": "throttle_log",
        },
    ]
}

REGIMES = ["post_hoc", "output_filter", "workflow_rules", "policy_as_code_only", "sarc"]


# ---------------------------------------------------------------------------
# Predicate and compatibility helpers
# ---------------------------------------------------------------------------


def applies(constraint: Dict[str, Any], state: Dict[str, Any], action: Dict[str, Any]) -> bool:
    if constraint["id"] == "ch_high_value_po":
        return action["tool"] == "erp.create_po" and action["amount"] >= 50000
    if constraint["id"] == "ce_first_time_supplier":
        return action["first_time_supplier"] is True
    if constraint["id"] == "cs_rolling_spend":
        return state["rolling_24h_spend"] >= 475000
    raise ValueError(constraint["id"])


def compatible(constraint: Dict[str, Any], observed_verif: str) -> bool:
    klass = constraint["class"]
    if klass == "hard":
        return observed_verif in {"PAG", "ATM", "tool_layer", "policy_layer"}
    if klass == "soft":
        return observed_verif in {"ATM", "PAA"}
    if klass == "escalation":
        return observed_verif in {"PAG", "PAA"}
    return False


def audit_trace(spec: Dict[str, Any], trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    discrepancies: List[Dict[str, Any]] = []
    constraints = {c["id"]: c for c in spec["constraints"]}
    for i, rec in enumerate(trace):
        state, action = rec["state"], rec["action"]
        evaluated = {e["id"]: e for e in rec["evaluated"]}
        for c in spec["constraints"]:
            if applies(c, state, action) and c["id"] not in evaluated:
                discrepancies.append(
                    {
                        "index": i,
                        "action_id": rec["action_id"],
                        "constraint": c["id"],
                        "type": "coverage",
                        "message": "Applicable constraint was not evaluated.",
                    }
                )
        for cid, ev in evaluated.items():
            c = constraints[cid]
            if not compatible(c, ev["verif"]):
                discrepancies.append(
                    {
                        "index": i,
                        "action_id": rec["action_id"],
                        "constraint": cid,
                        "type": "placement",
                        "message": f"Constraint evaluated at incompatible point {ev['verif']}.",
                    }
                )
            if ev["fired"] and ev["response"] != c["resp"]:
                discrepancies.append(
                    {
                        "index": i,
                        "action_id": rec["action_id"],
                        "constraint": cid,
                        "type": "response",
                        "message": "Fired constraint used a response different from specification.",
                    }
                )
        if not rec.get("attribution", {}).get("authority_nonempty", False):
            discrepancies.append(
                {
                    "index": i,
                    "action_id": rec["action_id"],
                    "constraint": None,
                    "type": "attribution",
                    "message": "Attribution chain has empty authority.",
                }
            )
    return discrepancies


# ---------------------------------------------------------------------------
# Episode simulation
# ---------------------------------------------------------------------------


def lognormal_amount(rng: random.Random) -> float:
    return rng.lognormvariate(8.5, 1.2)


def run_episode(
    seed: int,
    regime: str,
    n_orders: int = 1000,
    pred_noise: float = 0.0,
    exec_fail: float = 0.0,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    rolling = 0.0
    hard_executed = 0
    soft_overages = 0
    supplier_without_review = 0
    escalations = 0
    latency_ms = 0.0
    trace = []

    for i in range(n_orders):
        amount = lognormal_amount(rng)
        first_time = rng.random() < 0.135
        action = {
            "tool": "erp.create_po",
            "amount": amount,
            "first_time_supplier": first_time,
        }
        state = {"rolling_24h_spend": rolling}
        true_hard = amount >= 50000
        true_soft = rolling >= 475000
        executed = True
        reviewed = False
        evaluated = []

        if regime == "post_hoc":
            latency_ms += 0
        elif regime == "output_filter":
            latency_ms += 7
            if true_hard and rng.random() < 0.25:
                executed = False
                evaluated.append(
                    {
                        "id": "ch_high_value_po",
                        "verif": "PAA",
                        "fired": True,
                        "response": "block_or_escalate",
                    }
                )
        elif regime == "workflow_rules":
            latency_ms += 12
            if true_hard:
                evaluated.append(
                    {
                        "id": "ch_high_value_po",
                        "verif": "PAG",
                        "fired": True,
                        "response": "block_or_escalate",
                    }
                )
                executed = False
                reviewed = True
        elif regime == "policy_as_code_only":
            latency_ms += 15
            if true_hard and rng.random() > pred_noise:
                evaluated.append(
                    {
                        "id": "ch_high_value_po",
                        "verif": "policy_layer",
                        "fired": True,
                        "response": "block_or_escalate",
                    }
                )
                executed = False
                reviewed = True
            if first_time and rng.random() > pred_noise:
                evaluated.append(
                    {
                        "id": "ce_first_time_supplier",
                        "verif": "PAG",
                        "fired": True,
                        "response": "suspend_route_default_deny",
                    }
                )
                reviewed = True
                escalations += 1
        elif regime == "sarc":
            latency_ms += 21
            hard_fn = rng.random() < pred_noise
            exec_bypass = rng.random() < exec_fail
            if true_hard:
                evaluated.append(
                    {
                        "id": "ch_high_value_po",
                        "verif": "PAG",
                        "fired": not hard_fn,
                        "response": "block_or_escalate",
                    }
                )
                if not hard_fn and not exec_bypass:
                    executed = False
                    reviewed = True
                    escalations += 1
            if first_time:
                evaluated.append(
                    {
                        "id": "ce_first_time_supplier",
                        "verif": "PAG",
                        "fired": True,
                        "response": "suspend_route_default_deny",
                    }
                )
                reviewed = True
                escalations += 1
            if true_soft:
                evaluated.append(
                    {
                        "id": "cs_rolling_spend",
                        "verif": "PAA",
                        "fired": True,
                        "response": "throttle_log",
                    }
                )
        else:
            raise ValueError(regime)

        if executed:
            rolling += amount
            if true_hard:
                hard_executed += 1
            if first_time and not reviewed:
                supplier_without_review += 1
        if true_soft and regime not in {"sarc"}:
            soft_overages += 1
        elif true_soft and regime == "sarc":
            soft_overages += 1
            rolling *= 0.85

        trace.append(
            {
                "action_id": f"a{i}",
                "state": state,
                "action": action,
                "evaluated": evaluated,
                "attribution": {
                    "authority_nonempty": True,
                    "chain": ["principal", regime],
                },
            }
        )

    return {
        "regime": regime,
        "seed": seed,
        "hard_executed": hard_executed,
        "soft_overages": soft_overages,
        "supplier_without_review": supplier_without_review,
        "escalations": escalations,
        "latency_ms_per_step": latency_ms / n_orders,
        "audit_discrepancies": len(audit_trace(SPEC, trace)) if regime == "sarc" else None,
    }


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def ci95(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return 1.96 * stdev(xs) / math.sqrt(len(xs))


def _benchmark_rows(seeds: int, n_orders: int) -> List[Dict[str, Any]]:
    rows = []
    for seed in range(seeds):
        for regime in REGIMES:
            rows.append(run_episode(seed, regime, n_orders=n_orders))
    return rows


def _noise_sweep_rows(seeds: int, n_orders: int) -> List[Dict[str, Any]]:
    rows = []
    for pred_noise in [0, 0.01, 0.05, 0.10]:
        for exec_fail in [0, 0.01, 0.05]:
            for seed in range(seeds):
                r = run_episode(
                    seed,
                    "sarc",
                    n_orders=n_orders,
                    pred_noise=pred_noise,
                    exec_fail=exec_fail,
                )
                r["pred_noise"] = pred_noise
                r["exec_fail"] = exec_fail
                rows.append(r)
    return rows


def _write_csv(rows: List[Dict[str, Any]], path: pathlib.Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _summarise_benchmark(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary = []
    for regime in REGIMES:
        subset = [r for r in rows if r["regime"] == regime]
        for metric in [
            "hard_executed",
            "soft_overages",
            "supplier_without_review",
            "escalations",
            "latency_ms_per_step",
        ]:
            vals = [r[metric] for r in subset]
            summary.append(
                {
                    "regime": regime,
                    "metric": metric,
                    "mean": mean(vals),
                    "ci95": ci95(vals),
                }
            )
    return summary


def _summarise_noise(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary = []
    for pred_noise in [0, 0.01, 0.05, 0.10]:
        for exec_fail in [0, 0.01, 0.05]:
            subset = [
                r for r in rows if r["pred_noise"] == pred_noise and r["exec_fail"] == exec_fail
            ]
            vals = [r["hard_executed"] for r in subset]
            summary.append(
                {
                    "pred_noise": pred_noise,
                    "exec_fail": exec_fail,
                    "hard_executed_mean": mean(vals),
                    "hard_executed_ci95": ci95(vals),
                }
            )
    return summary


# ---------------------------------------------------------------------------
# Public callable API
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkConfig:
    """Configuration for run_benchmark().

    Parameters
    ----------
    seeds:
        Number of random seeds to run. Default 50 matches the paper.
    n_orders:
        Purchase orders simulated per episode. Default 1000 matches the paper.
        Use a much smaller value (e.g. 10) for fast CI smoke tests.
    """

    seeds: int = 50
    n_orders: int = 1000
    noise_sweep: bool = field(default=True)


def run_benchmark(config: BenchmarkConfig, output_dir: pathlib.Path) -> Dict[str, Any]:
    """Run the SARC paper benchmark and write output artifacts.

    Parameters
    ----------
    config:
        BenchmarkConfig controlling seeds, n_orders, and whether to run the noise sweep.
    output_dir:
        Directory to write output files. Created if it does not exist.

    Returns
    -------
    dict
        Summary with keys: n_cases, n_runs, seed, allow_count, block_count,
        escalation_count, benchmark_csv, noise_csv, summary_json, and the full
        nested benchmark/noise_sweep summaries.
    """
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_csv = output_dir / "sarc_eval_results.csv"
    summary_json = output_dir / "sarc_eval_summary.json"

    bench_rows = _benchmark_rows(config.seeds, config.n_orders)
    _write_csv(bench_rows, benchmark_csv)
    bench_summary = _summarise_benchmark(bench_rows)

    noise_rows: List[Dict[str, Any]] = []
    noise_summary: List[Dict[str, Any]] = []
    noise_csv = output_dir / "sarc_eval_noise_sweep.csv"
    if config.noise_sweep:
        noise_rows = _noise_sweep_rows(config.seeds, config.n_orders)
        _write_csv(noise_rows, noise_csv)
        noise_summary = _summarise_noise(noise_rows)

    # Aggregate SARC-regime stats for the summary top-level fields.
    sarc_rows = [r for r in bench_rows if r["regime"] == "sarc"]
    total_orders = config.seeds * config.n_orders
    total_hard_executed = sum(r["hard_executed"] for r in sarc_rows)
    total_escalations = sum(r["escalations"] for r in sarc_rows)

    summary: Dict[str, Any] = {
        "n_cases": len(bench_rows),
        "n_runs": config.seeds,
        "seed": config.seeds,
        "allow_count": total_orders - total_hard_executed,
        "block_count": total_hard_executed,
        "escalation_count": total_escalations,
        "benchmark_csv": str(benchmark_csv),
        "noise_csv": str(noise_csv) if config.noise_sweep else None,
        "summary_json": str(summary_json),
        "benchmark": bench_summary,
        "noise_sweep": noise_summary,
    }

    with open(summary_json, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


# ---------------------------------------------------------------------------
# CLI entry point (backward-compatible)
# ---------------------------------------------------------------------------


def benchmark(out_csv: str, seeds: int = 50, n_orders: int = 1000) -> List[Dict[str, Any]]:
    rows = _benchmark_rows(seeds, n_orders)
    _write_csv(rows, pathlib.Path(out_csv))
    return _summarise_benchmark(rows)


def noise_sweep(out_csv: str, seeds: int = 50, n_orders: int = 1000) -> List[Dict[str, Any]]:
    rows = _noise_sweep_rows(seeds, n_orders)
    _write_csv(rows, pathlib.Path(out_csv))
    return _summarise_noise(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="SARC paper evaluation benchmark")
    parser.add_argument("--benchmark", default="benchmarks/sarc_benchmark.csv")
    parser.add_argument("--noise", default="benchmarks/sarc_noise_sweep.csv")
    parser.add_argument("--summary", default="benchmarks/sarc_eval_summary.json")
    parser.add_argument("--seeds", type=int, default=50)
    parser.add_argument("--n-orders", type=int, default=1000, dest="n_orders")
    args = parser.parse_args()

    summary_data = {
        "benchmark": benchmark(args.benchmark, seeds=args.seeds, n_orders=args.n_orders),
        "noise_sweep": noise_sweep(args.noise, seeds=args.seeds, n_orders=args.n_orders),
    }
    with open(args.summary, "w") as f:
        json.dump(summary_data, f, indent=2)
    print(json.dumps(summary_data, indent=2))


if __name__ == "__main__":
    main()
