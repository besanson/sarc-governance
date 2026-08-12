# Copyright 2026 SARC Suite Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
SARC Suite One-Pass Demo: Main Simulation Engine

SEED = 26313
"""
import json
import csv
import random
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Any
from collections import defaultdict
from datetime import datetime, timedelta

from composition import (
    ActionContext,
    CompositionEngine,
    EvidenceSetLine,
    Response,
    is_executed,
)

# Constants
SEED = 26313
WARMUP = 35
INJECTION_PROBABILITY = 0.02


@dataclass
class ScenarioConfig:
    """Configuration for a scenario."""
    name: str
    allowed_roles: List[str]
    order_value_cap: float
    daily_cost_budget: float
    daily_carbon_budget: float
    constructed_cap_kappa: Dict[str, float]  # For S4: per decision sku@day -> cap


class RetailSimulation:
    """Main simulation engine for SARC Suite demo."""

    def __init__(self, data_path: str = "data/open_retail_daily.csv"):
        random.seed(SEED)
        self.data_path = Path(data_path)
        self.engine = CompositionEngine(mock_mode=True)
        self.data = self._load_data()
        self.dates = sorted(set(row["date"] for row in self.data))

    def _load_data(self) -> List[Dict[str, Any]]:
        """Load retail data."""
        data = []
        with open(self.data_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append({
                    "sku": row["sku"],
                    "date": row["date"],
                    "qty": float(row["qty"]),
                    "unit_price": float(row["unit_price"]),
                })
        return data

    def run_scenario(
        self,
        scenario: ScenarioConfig,
        composition_mode: str = "two_phase",
    ) -> tuple[List[EvidenceSetLine], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Run a scenario and return:
        - evidence_sets: list of EvidenceSetLine
        - run_log: list of ground-truth labels and defects
        - metrics: aggregated metrics
        """
        evidence_sets = []
        run_log = []
        metrics = {
            "decisions": 0,
            "admitted": 0,
            "held": 0,
            "veto_by_gate": {"dq": 0, "sarc": 0, "green": 0},
            "winner_gates": defaultdict(int),
            "defects_by_class": defaultdict(int),
        }

        # Compute SKU-specific economics
        sku_stats = self._compute_sku_stats()

        # Build decision stream: (day_idx, sku) pairs after warmup
        decisions = []
        for day_idx, date in enumerate(self.dates):
            if day_idx < WARMUP:
                continue
            for sku in sorted(set(row["sku"] for row in self.data)):
                # Get historical data for this SKU up to this day
                hist = [
                    row["qty"]
                    for row in self.data
                    if row["sku"] == sku and row["date"] <= date
                ]
                if hist:
                    decisions.append((day_idx, date, sku))

        # Process each decision
        for day_idx, date, sku in decisions:
            # Build context
            hist_data = [
                row for row in self.data if row["sku"] == sku and row["date"] <= date
            ]
            if not hist_data:
                continue

            # Compute newsvendor order (simplified: use trailing 28-day quantile)
            recent_qty = [row["qty"] for row in hist_data[-28:]]
            recent_qty.sort()
            order_idx = min(int(0.75 * len(recent_qty)), len(recent_qty) - 1)
            proposed_qty = recent_qty[order_idx] if recent_qty else 1

            # Get unit price and compute cost
            true_unit_cost = sku_stats[sku]["cost"]
            order_value = proposed_qty * true_unit_cost

            # Context
            context = ActionContext(
                agent_id=f"agent-{sku}",
                role=random.choice(scenario.allowed_roles) if random.random() > 0.05 else "unauthorized",
                sku=sku,
                day=day_idx,
                proposed_qty=proposed_qty,
                order_value=order_value,
                est_cost_eur=order_value * 1.2,  # Dummy overhead
                est_carbon_g=proposed_qty * 0.5,
            )

            # Create evidence records
            evidence_records = self._create_evidence_records(
                sku, date, true_unit_cost, day_idx
            )

            # Governed buffer (true costs)
            governed_buffer = {"true_unit_cost": true_unit_cost}

            # Evaluate composition
            if composition_mode == "two_phase":
                evidence_set = self.engine.two_phase_composition(
                    context,
                    evidence_records,
                    governed_buffer,
                    scenario.allowed_roles,
                    scenario.order_value_cap,
                    scenario.daily_cost_budget,
                    scenario.daily_carbon_budget,
                )
            else:  # single_pass
                evidence_set = self.engine.single_pass_composition(
                    context,
                    evidence_records,
                    governed_buffer,
                    scenario.allowed_roles,
                    scenario.order_value_cap,
                    scenario.daily_cost_budget,
                    scenario.daily_carbon_budget,
                )

            # For S4: potentially override cap
            if scenario.constructed_cap_kappa:
                key = f"{sku}@{day_idx}"
                if key in scenario.constructed_cap_kappa:
                    scenario.order_value_cap = scenario.constructed_cap_kappa[key]

            evidence_sets.append(evidence_set)

            # Log ground truth
            run_log.append({
                "day": day_idx,
                "sku": sku,
                "decision_id": len(run_log),
                "ground_truth": {
                    "true_unit_cost": true_unit_cost,
                    "injected_defect": self._last_injected_defect,
                },
                "verdict": evidence_set.final["response"],
                "winner_gate": evidence_set.final["winner_gate"],
            })

            # Update metrics
            metrics["decisions"] += 1
            if evidence_set.final["admitted"]:
                metrics["admitted"] += 1
            else:
                metrics["held"] += 1

            winner = evidence_set.final["winner_gate"]
            if winner in metrics["veto_by_gate"]:
                metrics["veto_by_gate"][winner] += 1
            metrics["winner_gates"][winner] += 1

            if self._last_injected_defect:
                metrics["defects_by_class"][self._last_injected_defect] += 1

        return evidence_sets, run_log, metrics

    def _compute_sku_stats(self) -> Dict[str, Dict[str, float]]:
        """Compute per-SKU statistics (sell price, cost)."""
        sku_prices = defaultdict(list)
        for row in self.data:
            sku_prices[row["sku"]].append(row["unit_price"])

        stats = {}
        for sku, prices in sku_prices.items():
            prices.sort()
            median_price = prices[len(prices) // 2]
            stats[sku] = {
                "sell_price": median_price,
                "cost": median_price * 0.6,  # true cost = 0.6 x price
            }
        return stats

    def _create_evidence_records(
        self, sku: str, date: str, true_unit_cost: float, day_idx: int
    ) -> List[Dict[str, Any]]:
        """Create evidence records with potential defects injected."""
        self._last_injected_defect = None
        records = []

        # Primary record
        primary_record = {
            "record_id": f"{sku}-primary",
            "payload": {
                "sku": sku,
                "unit_cost": true_unit_cost,
                "currency": "GBP",
            },
            "metadata": {
                "source": "erp.pricing",
                "as_of_day": day_idx,
                "retrieved_day": day_idx,
                "version": 2,
                "lineage": ("supplier_feed:SKU",),
            },
        }

        # Inject at most one defect (probability 0.02)
        if random.random() < INJECTION_PROBABILITY:
            defect_class = random.choice([
                "stale_master_data",
                "superseded_golden_record",
                "cross_source_contradiction",
                "schema_drift",
                "missing_mandatory_field",
                "lineage_missing",
                "plausible_outlier",
            ])

            if defect_class == "stale_master_data":
                # as_of_day set 45-150 days behind, cost 0.55-0.9x
                staleness = random.randint(45, 150)
                old_cost = true_unit_cost * random.uniform(0.55, 0.9)
                primary_record["metadata"]["as_of_day"] = day_idx - staleness
                primary_record["payload"]["unit_cost"] = old_cost
                self._last_injected_defect = defect_class

            elif defect_class == "superseded_golden_record":
                # Add a second record with version 1
                v1_record = {
                    "record_id": f"{sku}-golden",
                    "payload": {
                        "sku": sku,
                        "unit_cost": true_unit_cost * 0.8,
                        "currency": "GBP",
                    },
                    "metadata": {
                        "source": "erp.pricing",
                        "as_of_day": day_idx - 10,
                        "retrieved_day": day_idx,
                        "version": 1,
                        "lineage": ("supplier_feed:SKU",),
                    },
                }
                records.append(v1_record)
                self._last_injected_defect = defect_class

            elif defect_class == "schema_drift":
                primary_record["payload"]["unit_cost"] = str(true_unit_cost)
                self._last_injected_defect = defect_class

            elif defect_class == "missing_mandatory_field":
                del primary_record["payload"]["currency"]
                self._last_injected_defect = defect_class

            elif defect_class == "lineage_missing":
                primary_record["metadata"]["source"] = ""
                self._last_injected_defect = defect_class

            elif defect_class == "plausible_outlier":
                primary_record["payload"]["unit_cost"] = true_unit_cost * 2.5
                # Keep metadata clean
                self._last_injected_defect = defect_class

            elif defect_class == "cross_source_contradiction":
                # Add a conflicting source
                alt_record = {
                    "record_id": f"{sku}-alt",
                    "payload": {
                        "sku": sku,
                        "unit_cost": true_unit_cost * 1.03,
                        "currency": "GBP",
                    },
                    "metadata": {
                        "source": "supplier_api",
                        "as_of_day": day_idx,
                        "retrieved_day": day_idx,
                        "version": 2,
                        "lineage": ("api.supplier",),
                    },
                }
                records.append(alt_record)
                self._last_injected_defect = defect_class

        records.insert(0, primary_record)
        return records

    def post_hoc_audit(
        self, evidence_sets: List[EvidenceSetLine]
    ) -> Dict[str, Any]:
        """
        Post-hoc audit: re-evaluate every gate on executed action.
        Returns audit results.
        """
        violations = 0
        for evidence_set in evidence_sets:
            # Check if any gate would reject the executed action
            # (this is simplified; real audit would replay full state)
            action = evidence_set.action
            if action["order_qty"] > 100:  # Arbitrary threshold
                violations += 1
        return {"total_violations": violations}

    def write_evidence_sets(
        self, evidence_sets: List[EvidenceSetLine], output_file: str
    ):
        """Write evidence sets to JSONL file."""
        with open(output_file, "w") as f:
            for es in evidence_sets:
                f.write(json.dumps(es.to_dict()) + "\n")

    def write_run_log(self, run_log: List[Dict[str, Any]], output_file: str):
        """Write run log with ground truth to JSONL."""
        with open(output_file, "w") as f:
            for entry in run_log:
                f.write(json.dumps(entry) + "\n")

    def get_data_hash(self) -> str:
        """Return SHA256 of the data file."""
        with open(self.data_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
