import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from statistics import mean, stdev


@dataclass
class Constraint:
    cid: str
    klass: str
    predicate: str
    verif: str
    resp: str


SPEC = {
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


def applies(constraint, state, action):
    if constraint["id"] == "ch_high_value_po":
        return action["tool"] == "erp.create_po" and action["amount"] >= 50000
    if constraint["id"] == "ce_first_time_supplier":
        return action["first_time_supplier"] is True
    if constraint["id"] == "cs_rolling_spend":
        return state["rolling_24h_spend"] >= 475000
    raise ValueError(constraint["id"])


def compatible(constraint, observed_verif):
    klass = constraint["class"]
    if klass == "hard":
        return observed_verif in {"PAG", "ATM", "tool_layer", "policy_layer"}
    if klass == "soft":
        return observed_verif in {"ATM", "PAA"}
    if klass == "escalation":
        return observed_verif in {"PAG", "PAA"}
    return False


def audit_trace(spec, trace):
    discrepancies = []
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


def lognormal_amount(rng):
    return rng.lognormvariate(8.5, 1.2)


def run_episode(seed, regime, n_orders=1000, pred_noise=0.0, exec_fail=0.0):
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
        action = {"tool": "erp.create_po", "amount": amount, "first_time_supplier": first_time}
        state = {"rolling_24h_spend": rolling}
        true_hard = amount >= 50000
        true_soft = rolling >= 475000
        true_escalation = first_time
        executed = True
        reviewed = False
        evaluated = []

        if regime == "post_hoc":
            latency_ms += 0
        elif regime == "output_filter":
            latency_ms += 7
            # Text filters do not see the side-effectful action reliably.
            if true_hard and rng.random() < 0.25:
                executed = False
                evaluated.append({"id": "ch_high_value_po", "verif": "PAA", "fired": True, "response": "block_or_escalate"})
        elif regime == "workflow_rules":
            latency_ms += 12
            # Static workflow rules catch registered high-value PO but not supplier and soft window.
            if true_hard:
                evaluated.append({"id": "ch_high_value_po", "verif": "PAG", "fired": True, "response": "block_or_escalate"})
                executed = False
                reviewed = True
        elif regime == "policy_as_code_only":
            latency_ms += 15
            # Generic policy catches high-value and supplier if rules are registered, but no trace-class completeness.
            if true_hard and rng.random() > pred_noise:
                evaluated.append({"id": "ch_high_value_po", "verif": "policy_layer", "fired": True, "response": "block_or_escalate"})
                executed = False
                reviewed = True
            if first_time and rng.random() > pred_noise:
                evaluated.append({"id": "ce_first_time_supplier", "verif": "PAG", "fired": True, "response": "suspend_route_default_deny"})
                reviewed = True
                escalations += 1
        elif regime == "sarc":
            latency_ms += 21
            hard_fn = rng.random() < pred_noise
            exec_bypass = rng.random() < exec_fail
            if true_hard:
                evaluated.append({"id": "ch_high_value_po", "verif": "PAG", "fired": not hard_fn, "response": "block_or_escalate"})
                if not hard_fn and not exec_bypass:
                    executed = False
                    reviewed = True
                    escalations += 1
            if first_time:
                evaluated.append({"id": "ce_first_time_supplier", "verif": "PAG", "fired": True, "response": "suspend_route_default_deny"})
                reviewed = True
                escalations += 1
            if true_soft:
                evaluated.append({"id": "cs_rolling_spend", "verif": "PAA", "fired": True, "response": "throttle_log"})
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
            # PAA throttling reduces subsequent overage exposure.
            soft_overages += 1
            rolling *= 0.85

        trace.append(
            {
                "action_id": f"a{i}",
                "state": state,
                "action": action,
                "evaluated": evaluated,
                "attribution": {"authority_nonempty": True, "chain": ["principal", regime]},
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


def ci95(xs):
    if len(xs) < 2:
        return 0
    return 1.96 * stdev(xs) / math.sqrt(len(xs))


def benchmark(out_csv, seeds=50):
    regimes = ["post_hoc", "output_filter", "workflow_rules", "policy_as_code_only", "sarc"]
    rows = []
    for seed in range(seeds):
        for regime in regimes:
            rows.append(run_episode(seed, regime))
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = []
    for regime in regimes:
        subset = [r for r in rows if r["regime"] == regime]
        for metric in ["hard_executed", "soft_overages", "supplier_without_review", "escalations", "latency_ms_per_step"]:
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


def noise_sweep(out_csv, seeds=50):
    rows = []
    for pred_noise in [0, 0.01, 0.05, 0.10]:
        for exec_fail in [0, 0.01, 0.05]:
            for seed in range(seeds):
                r = run_episode(seed, "sarc", pred_noise=pred_noise, exec_fail=exec_fail)
                r["pred_noise"] = pred_noise
                r["exec_fail"] = exec_fail
                rows.append(r)
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for pred_noise in [0, 0.01, 0.05, 0.10]:
        for exec_fail in [0, 0.01, 0.05]:
            subset = [r for r in rows if r["pred_noise"] == pred_noise and r["exec_fail"] == exec_fail]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="/home/user/workspace/sarc_benchmark.csv")
    parser.add_argument("--noise", default="/home/user/workspace/sarc_noise_sweep.csv")
    parser.add_argument("--summary", default="/home/user/workspace/sarc_eval_summary.json")
    args = parser.parse_args()

    summary = {
        "benchmark": benchmark(args.benchmark),
        "noise_sweep": noise_sweep(args.noise),
    }
    with open(args.summary, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
