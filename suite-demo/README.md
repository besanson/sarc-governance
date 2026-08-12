# SARC Suite One-Pass Demo

## Honesty Banner

**Mechanism demonstration on open payload data with a declared synthetic metadata layer. Not a live GIGO-Bench release; live cells come only from the official harness. Not the proprietary Suite: no connectors, evidence vault, identity, or hosting. plausible_outlier is injected and not caught, by design: declared uncovered. S4 is a constructed counterexample scenario, declared as such.**

## Overview

This demo composes three open Apache 2.0 governance engines at one Pre-Action control point over an open-data replenishment stream:

- **sarc-governance** (arXiv 2605.07728): obligations and permissions gate
- **Greensarc** (arXiv 2606.15954): predictive cost and carbon budgets gate
- **sarc-dq** (arXiv 2607.26313): metadata evidence-quality gate

The composition demonstrates:
1. **Min semantics** across gates (restrictiveness join: admit < substitute < degrade < escalate < block)
2. **Two-phase protocol** for sound remediation under evidence substitution
3. **Unified Evidence Set** per decision preserving cross-gate lineage
4. **Declared-uncovered coverage**: plausible_outlier is injected and remains uncovered

## Running the Demo

### Prerequisites
```bash
python3 --version              # need 3.11+
pip install -e ./dqSarc[gate]
pip install -e ./sarc-governance
pip install -e ./Greensarc
pip install pytest
```

### Build and Test
```bash
make test      # Run 11-test suite (all must pass)
make suite     # Run all four scenarios S1-S4 in both modes (~20 seconds)
make paper     # Generate paper draft v0.2 with filled slots
make clean     # Remove outputs
```

## Files

- **suite_sim.py**: Main simulation engine (decision stream, defect injection)
- **composition.py**: Three-gate orchestration (two-phase and single-pass protocols)
- **runner.py**: Scenario runner (S1-S4 configurations)
- **paper_tables.py**: Generate table data for paper
- **populate_draft.py**: Fill paper draft template with generated numbers
- **specs/authority.yaml**: SARC governance specification
- **test_suite_sim.py**: Comprehensive test suite
- **data/**: UCI Online Retail dataset (CC BY 4.0)
- **out/**: Output artifacts (evidence sets, metrics, paper)

## Data

**Source**: UCI Online Retail (CC BY 4.0)
- Citation: Chen, D. (2015). Online Retail [Dataset]. UCI Machine Learning Repository. doi 10.24432/C5BW33.
- Filtered to UK, Quantity > 0, UnitPrice > 0
- Aggregated per (SKU, date): 40 top SKUs by active days
- PROVENANCE: data/PROVENANCE.md

## Scenarios

### S1: Baseline
- Loose budgets, all roles authorised
- Expected: zero sarc and zero green vetoes; DQ behaviour dominates

### S2: Tight-budget day
- Budgets sized to trigger green vetoes
- Expected: green veto rate > 0 on known subset

### S3: Unauthorised burst
- 5% decisions from non-allowlisted role
- Low order_value_cap
- Expected: sarc vetoes > 0 including on clean evidence

### S4: Constructive counterexample (Proposition 3)
- Authority cap kappa strictly between pre- and post-substitution order values
- Run in both two-phase and single-pass modes
- Expected: divergent verdicts, CH2 confirmed

## Composition Protocols

### Two-Phase (Sound)
1. **Phase I**: Evaluate evidence gate; on substitution, recompute context
2. **Phase II**: Evaluate all gates on remediated action; return join
3. **Termination**: Idempotent substitution guarantees fixed point after ≤1 remediation

### Single-Pass (Measurement)
- Evaluate all gates once on original action
- Executed action still uses remediated value if DQ substituted
- Used to measure divergence vs two-phase (CH2)

## Hypotheses (Pre-registered)

- **CH1** (veto soundness): Post-hoc audit finds zero violations under two-phase
- **CH2** (single-pass unsoundness is real): S4 divergences observed
- **CH3** (deterministic selectivity): Zero false holds on clean/auth/budget decisions
- **CH4** (coverage honesty): plausible_outlier stays uncovered; union property holds

## Determinism & Reproducibility

- **SEED = 26313** everywhere
- **Deterministic predicates**: no LLM calls, no API spend
- **Zero source writes**: proven by SHA256 before/after
- **Downstream-only remediation**: governed buffer substitution only
- All randomness seeded: same runs produce byte-identical metrics

## Definition of Done

✓ `make test` green (all 11 tests)
✓ `make suite` completes <20s, prints scenario summaries
✓ `make paper` produces v0.2 with zero unfilled slots
✓ Honesty banners verbatim in README, readouts, populated draft
✓ ADR-001-composition.md written
✓ Apache-2.0 headers on all new files
✓ Three repos untouched (`git status --porcelain` empty)
✓ Final console lists all artifact paths

## License

Apache License 2.0

All new files: Apache-2.0 headers present
Data: CC BY 4.0 (UCI Online Retail)
Composed engines: Apache-2.0 (sarc-governance, Greensarc, sarc-dq)
