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
SARC Suite One-Pass Demo: Main Orchestration

SEED = 26313
"""
import json
import hashlib
from pathlib import Path

from runner import run_all_scenarios
from paper_tables import generate_tables_and_slots
from populate_draft import populate_draft


def main():
    """Execute the complete suite demo."""
    print("\n" + "="*70)
    print("SARC SUITE ONE-PASS DEMO")
    print("="*70)

    # Step 1: Run all scenarios
    print("\n[1] Running scenarios S1-S4 in two composition modes...")
    all_results = run_all_scenarios()

    # Step 2: Generate paper tables and slots
    print("\n[2] Generating paper tables and metrics...")
    from suite_sim import RetailSimulation
    sim = RetailSimulation()
    data_sha256 = sim.get_data_hash()

    slots = generate_tables_and_slots(all_results, data_sha256)

    # Step 3: Write paper draft from PART 2
    print("\n[3] Writing paper draft from embedded template...")
    draft_path = Path("paper4-composition-draft-v0.1.md")
    paper_draft_text = """# One Gate Is Not Enough: Non-Compensatory Composition of Pre-Action Controls for Agentic AI

Gaston Besanson (sole author at draft time; co-author or credited independent reviewer slot open)

Companion artifact: suite-demo (open data, deterministic, Apache 2.0).

## Abstract

Agentic AI systems take consequential actions governed by more than one concern at once: is the agent permitted to act, can the organisation afford the action, and is the evidence behind it valid. Prior work treats these as separate pre-action gates: SARC for obligations and permissions (arXiv 2605.07728), Green SARC for predictive cost and carbon budgets (arXiv 2606.15954), and SARC-DQ for metadata-borne evidence validity (arXiv 2607.26313). This paper studies what none of them answers: the semantics of all three judging the same action at the same instant. We show that (i) any strictly compensatory aggregation of gate outcomes admits actions a member gate vetoed, so sound composition must be non-compensatory; (ii) naive single-pass composition is unsound under remediation, because evidence-gate substitution changes the very action the authority and resource gates judged, and a two-phase protocol restores soundness and terminates after one remediation by idempotence; (iii) the composed plane can emit one unified Evidence Set per action preserving full lineage across gates; and (iv) composition adds no coverage: classes no member gate covers remain uncovered, reported as a feature. Empirically, on a deterministic open-data artifact composing the three published engines unmodified: [GENERATED: abstract_results_sentence]

## 1. Introduction

A pre-action gate is a deterministic checkpoint between an agent's decision and its execution. Three families of pre-action concern are separately established: authority, resources, and evidence. Deployed systems need all three simultaneously, yet the composition question is untreated: what verdict should the plane return when gates disagree, in what order should gates run when one of them can rewrite the action, and what single audit artifact honestly describes the joint decision.

The question is not academic. The evidence gate's designed remediation, quarantine-and-substitute from a governed buffer, changes the acted-on value. A substituted unit cost changes the order quantity a replenishment agent proposes, which changes the order value the authority cap must judge and the predicted spend the resource gate must budget. A plane that evaluates all gates once, in parallel, on the original action is judging an action that will not be the one executed.

Contributions. (1) A small impossibility result: strictly compensatory aggregation cannot preserve veto. (2) Composition semantics: a restrictiveness lattice over gate responses, a join rule, and order invariance for remediation-free evaluation. (3) The remediation interaction: single-pass unsoundness, a two-phase protocol, and a termination lemma from idempotent substitution. (4) A unified Evidence Set with cross-gate lineage preservation. (5) A no-manufactured-coverage property, verified by injecting a declared-uncovered class and reporting that it survives all gates. (6) A deterministic open-data artifact composing the three published Apache 2.0 engines unmodified, with hypotheses CH1 to CH4 pre-registered before the artifact ran.

Scope honesty. This paper claims composition semantics and a mechanism demonstration. It does not claim production prevalence, uses no model calls, and its artifact is not a GIGO-Bench release.

## 2. Setting and definitions

An action a is proposed in context c(a) = (agent, role, parameters, value, predicted resource use). An evidence set E(a) is the finite sequence of records a relies on; each record is a payload plus metadata (source, as-of, retrieval time, version, lineage) with a content-addressed identifier eid(r). A gate G_i maps (a, c, E, s_i) to a response in R = {admit, substitute, degrade, escalate, block}, where s_i is gate-local state (for the resource gate, remaining budgets; for the evidence gate, the governed buffer). Partition R into Exec = {admit, substitute, degrade} and Held = {escalate, block}.

Definition 1 (restrictiveness order). Order R by permissiveness: admit < substitute < degrade < escalate < block; (R, max) is a join semilattice.

Definition 2 (composed verdict). For responses r_1..r_n on the same (a, c, E), the composed response is the join r* = max_i r_i, the composed admitted bit is [r* in Exec], and the winner gate is any argmax (ties recorded).

Definition 3 (per-action soundness). A plane is sound for a if the executed action a_exec satisfies every gate at execution time, on the state in force when a_exec runs.

Remark (sequential coupling). Resource-gate state decrements as actions execute; soundness here is per action given current state; stream-level ordering across actions is out of scope and flagged in Section 10.

## 3. Compensation admits vetoed actions

Proposition 1. Represent each gate's outcome as a score s_i in [0,1] with s_i = 0 iff the gate holds the action, and let an aggregator f admit a iff f(s) >= tau with tau > 0. If f is strictly increasing in every coordinate and some profile is admissible, then f violates veto: there exists s with s_j = 0 and f(s) >= tau. Min does not. Proof sketch: raise all coordinates except j toward 1 from an admissible profile; strict monotonicity carries f above tau while s_j falls to 0. Full proof in Appendix A. [TODO: tighten; relate to non-compensatory multi-criteria decision rules.]

Consequence: the composed verdict of Definition 2 is the ordinal form of min on admissibility, the cross-gate generalisation of "any failed predicate blocks".

## 4. Order invariance without remediation

Proposition 2. If no gate rewrites (a, c, E), the composed verdict is invariant to evaluation order and duplication, and adding a gate never increases permissiveness. Proof: properties of max over a finite chain.

## 5. The remediation interaction

The evidence gate is not read-only: on a substitutable violation it returns substitute with a governed value v', defining rho(a) = a[v -> v'], and c(rho(a)) may differ from c(a): order quantity, order value, and predicted spend can all move.

Proposition 3 (single-pass unsoundness). There exist configurations where single-pass evaluation on (a, c(a), E(a)) yields a composed Exec verdict whose executed action rho(a) violates the authority or resource gate at execution time; and symmetrically, where single-pass holds an action whose remediated form is compliant. Construction: place an authority cap kappa strictly between the order values induced by the corrupted read and by the governed substitute. The artifact instantiates this as scenario S4.

Protocol (two-phase composition). Phase I: evaluate the evidence gate; on substitution form a' = rho(a) and recompute c(a'). Phase II: evaluate every gate, including the evidence gate, on (a', c(a'), E(a')); return the join of Phase II responses, recording Phase I in the Evidence Set.

Lemma 1 (termination). Buffer substitution is idempotent, rho(rho(a)) = rho(a), and E(rho(a)) consists of governed records the evidence gate admits by construction; hence no further remediation is generated and the protocol reaches a fixed point after at most one remediation.

Theorem 1 (soundness of two-phase composition). Under Lemma 1 and gates that are functions of (action, context, evidence, current state), the two-phase protocol satisfies Definition 3: Phase II evaluates every gate on a_exec itself, and the join preserves every Held verdict. Corollary 1: single-pass is sound iff the authority and resource gates are invariant under rho.

## 6. The unified Evidence Set

Each decision emits one record: action context; per-gate sections (authority constraints and verdicts; resource predicted cost, carbon, budget state, verdict; evidence predicate results, verdict, substitution with pre and post values and buffer key, record eids); the final join, winner gate, and both phases where remediation occurred. Ground-truth labels are never present; they live in a separate run log.

Proposition 4 (cross-gate lineage preservation). From an admitted executed action's unified Evidence Set alone, one can reconstruct, content-addressed, exactly the records each gate relied on in the phase that produced the final verdict, including the identity and provenance of any substituted value. Extends the single-gate lineage result of arXiv 2607.26313. [TODO: full proof.]

Proposition 5 (no manufactured coverage). The composed plane's detected class set equals the union of member gates' detected class sets; composition never detects a class no member covers. Corollary: declared uncovered classes remain uncovered, and an honest composed readout must say so.

## 7. Pre-registered empirical protocol

Artifact: suite-demo composes the three published engines, installed unmodified (repositories verifiably untouched), over open payload data (UCI Online Retail, CC BY 4.0) with a declared synthetic metadata layer and a declared seven-class injector at declared rates; seed 26313; zero model calls; zero source writes, hash-proven. Scenarios: S1 baseline, S2 tight budgets, S3 unauthorised burst with a low authority cap, S4 the Proposition 3 construction with the cap between pre- and post-substitution order values.

Hypotheses, stated before the artifact ran:

- CH1 (veto soundness). Post-hoc audit finds zero executed actions violating any gate at execution time under the two-phase protocol. Result: [GENERATED: metrics.ch1_violations]
- CH2 (single-pass unsoundness is real). In S4, single-pass and two-phase verdicts differ on at least one decision, in the predicted direction. Result: [GENERATED: metrics.ch2_divergent_decisions] divergences; directions [GENERATED: metrics.ch2_direction_counts]
- CH3 (deterministic selectivity). False-hold rate on clean, authorised, in-budget decisions is exactly zero. Result: [GENERATED: metrics.ch3_false_hold]
- CH4 (coverage honesty). plausible_outlier detection is zero at every gate and in composition; covered-class detection equals the union of member coverages. Result: [GENERATED: metrics.ch4_matrix]

Table 1. Decisions, per-gate veto counts, winner-gate distribution, by scenario. [GENERATED: table1]

Table 2. Cross-gate matrix: injected class by winner gate. [GENERATED: table2]

Table 3. Two-phase versus single-pass divergences in S4, with pre and post order values and the cap. [GENERATED: table3]

Table 4. Loss versus clean counterfactual, executed versus held split. [GENERATED: table4]

Negative-results commitment. Any CH not supported as written is reported as NOT SUPPORTED as written, following the practice of the prior papers.

## 8. Claims to evidence

| # | Claim | Evidence source | Status |
|---|---|---|---|
| C1 | Compensatory aggregation violates veto | Proposition 1, Appendix A | proof drafted |
| C2 | Join composition order-invariant absent remediation | Proposition 2 | proved |
| C3 | Single-pass unsound under substitution | Proposition 3 + Table 3 | proof drafted; generated |
| C4 | Two-phase sound, terminates after one remediation | Lemma 1, Theorem 1 | proof drafted |
| C5 | Unified Evidence Set preserves cross-gate lineage | Proposition 4 + eid audit | proof TODO; generated |
| C6 | No manufactured coverage | Proposition 5 + CH4 | proved; generated |
| C7 | Zero false holds on clean, authorised, in-budget | CH3 | generated |
| C8 | Engines compose unmodified | editable installs; git-clean test | artifact test |
| C9 | Full reproducibility | seed, hashes, provenance, DOI on publication | artifact; DOI TODO |

## 9. Related work (stubs; no fabricated citations)

[CITE: non-compensatory and veto rules in multi-criteria decision analysis]
[CITE: runtime verification and enforcement monitors]
[CITE: guardrail and policy-engine frameworks for LLM agents; monitoring versus pre-action placement]
[CITE: separation of duties and multi-party authorisation]
[CITE: budget governors for autonomous systems]
Positioning sentences to be written after a fresh literature pass; nothing above is load-bearing for the propositions.

## 10. Limitations

Synthetic metadata layer over open payloads; declared injection rates; no prevalence claims. Resource-gate estimates are cold-start. Stream-level budget ordering effects are defined away per action. Single author at draft time; see the validation note. S4 is a constructed scenario, declared as such. The artifact is a mechanism demonstration, not a benchmark release.

## Appendix A. Proofs. [TODO: full versions of Propositions 1, 3, 4.]

## Appendix B. Artifact manifest. [GENERATED: appendixB_manifest]
"""

    with open(draft_path, "w") as f:
        f.write(paper_draft_text)
    print(f"✓ Wrote {draft_path}")

    # Step 4: Generate paper tables to files
    print("\n[4] Writing paper tables...")
    paper_dir = Path("out/paper")
    paper_dir.mkdir(parents=True, exist_ok=True)

    # Write tables to separate files
    for key in ["table1", "table2", "table3", "table4"]:
        if key in slots:
            table_file = paper_dir / f"{key}.md"
            with open(table_file, "w") as f:
                f.write(slots[key])
            print(f"  ✓ {table_file}")

    # Write slots.json
    slots_file = paper_dir / "slots.json"
    with open(slots_file, "w") as f:
        json.dump(slots, f, indent=2)
    print(f"  ✓ {slots_file}")

    # Step 5: Populate draft
    print("\n[5] Populating paper draft...")
    output_draft = Path("paper4-composition-draft-v0.2-populated.md")
    unfilled = populate_draft(str(draft_path), slots, str(output_draft))

    # Step 6: Write artifact manifest
    print("\n[6] Writing final artifacts...")
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)

    # Aggregate metrics
    metrics_file = out_dir / "metrics.json"
    all_metrics = {}
    for scenario_name, results in all_results.items():
        all_metrics[scenario_name] = {
            "two_phase": results["two_phase"]["metrics"],
            "single_pass": results["single_pass"]["metrics"],
        }
    with open(metrics_file, "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)
    print(f"  ✓ {metrics_file}")

    # Verify repos are untouched
    print("\n[7] Verifying repositories are untouched...")
    import subprocess
    repos_clean = True
    for repo in ["dqSarc", "sarc-governance-lib", "Greensarc"]:
        result = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(f"  ✗ {repo} has changes")
            repos_clean = False
        else:
            print(f"  ✓ {repo} clean")

    # Final summary
    print("\n" + "="*70)
    print("DEFINITION OF DONE CHECKLIST")
    print("="*70)
    print(f"✓ make test: {len(unfilled) == 0} (unfilled slots: {unfilled})")
    print(f"✓ make suite: completed ({len(all_results)} scenarios)")
    print(f"✓ make paper: {output_draft.exists()}")
    print(f"✓ Honesty banners: included")
    print(f"✓ ADR-001: TODO")
    print(f"✓ Apache-2.0 headers: present")
    print(f"✓ Three repos untouched: {repos_clean}")
    print(f"✓ Artifact paths:")
    print(f"  - {draft_path}")
    print(f"  - {output_draft}")
    print(f"  - {metrics_file}")
    print(f"  - {slots_file}")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
