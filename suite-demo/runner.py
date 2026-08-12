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
SARC Suite Runner: Execute all scenarios in two composition modes.

SEED = 26313
"""
import json
import hashlib
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any

from suite_sim import RetailSimulation, ScenarioConfig

SEED = 26313


def run_all_scenarios():
    """Run all four scenarios (S1-S4) in both composition modes."""
    sim = RetailSimulation()
    data_hash_before = sim.get_data_hash()

    # Define scenarios
    scenarios = {
        "S1": ScenarioConfig(
            name="S1 baseline",
            allowed_roles=["agent-S1", "agent-replenish"],
            order_value_cap=10000.0,
            daily_cost_budget=50000.0,
            daily_carbon_budget=50000.0,
            constructed_cap_kappa={},
        ),
        "S2": ScenarioConfig(
            name="S2 tight-budget day",
            allowed_roles=["agent-S2", "agent-replenish"],
            order_value_cap=10000.0,
            daily_cost_budget=5000.0,  # Tighter budget
            daily_carbon_budget=5000.0,
            constructed_cap_kappa={},
        ),
        "S3": ScenarioConfig(
            name="S3 unauthorised burst",
            allowed_roles=["agent-S3"],  # Narrower allowed roles
            order_value_cap=1000.0,  # Low cap
            daily_cost_budget=50000.0,
            daily_carbon_budget=50000.0,
            constructed_cap_kappa={},
        ),
        "S4": ScenarioConfig(
            name="S4 constructive counterexample",
            allowed_roles=["agent-S4", "agent-replenish"],
            order_value_cap=10000.0,  # Default (may be overridden per decision)
            daily_cost_budget=50000.0,
            daily_carbon_budget=50000.0,
            constructed_cap_kappa={},  # Built during run
        ),
    }

    # Output directory
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)

    all_results = {}

    # Run each scenario in both modes
    for scenario_name, scenario_config in scenarios.items():
        print(f"\n{'='*60}")
        print(f"Running {scenario_name}: {scenario_config.name}")
        print(f"{'='*60}")

        scenario_results = {}

        for composition_mode in ["two_phase", "single_pass"]:
            print(f"  {composition_mode}...", end=" ", flush=True)

            # For S4, build the constructed_cap_kappa
            if scenario_name == "S4" and composition_mode == "two_phase":
                # Pre-compute caps between pre and post substitution values
                # This is simplified; would need actual execution
                pass

            evidence_sets, run_log, metrics = sim.run_scenario(
                scenario_config, composition_mode
            )

            scenario_results[composition_mode] = {
                "evidence_sets": evidence_sets,
                "run_log": run_log,
                "metrics": dict(metrics),
            }

            print(f"✓ ({len(evidence_sets)} decisions)")

        # Persist results
        scenario_dir = out_dir / scenario_name
        scenario_dir.mkdir(exist_ok=True)

        for mode, result in scenario_results.items():
            # Write evidence sets
            evidence_file = scenario_dir / f"{mode}-evidence.jsonl"
            sim.write_evidence_sets(result["evidence_sets"], str(evidence_file))

            # Write run log
            log_file = scenario_dir / f"{mode}-runlog.jsonl"
            sim.write_run_log(result["run_log"], str(log_file))

            # Write metrics
            metrics_file = scenario_dir / f"{mode}-metrics.json"
            with open(metrics_file, "w") as f:
                json.dump(result["metrics"], f, indent=2, default=str)

        all_results[scenario_name] = scenario_results

    # Aggregate metrics
    data_hash_after = sim.get_data_hash()
    assert data_hash_before == data_hash_after, "Data file was modified!"

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for scenario_name, results in all_results.items():
        two_phase = results["two_phase"]["metrics"]
        single_pass = results["single_pass"]["metrics"]
        print(
            f"{scenario_name}: decisions={two_phase['decisions']}, "
            f"admitted={two_phase['admitted']}, held={two_phase['held']}"
        )

    print(f"\nData hash: {data_hash_before}")
    print(f"Data unchanged: {data_hash_before == data_hash_after}")

    return all_results


if __name__ == "__main__":
    results = run_all_scenarios()
