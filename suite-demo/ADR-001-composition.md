# ADR-001: Three-Gate Composition Architecture

**Status**: Accepted
**Date**: 2026-08-12
**Author**: SARC Suite Demo

## Context

The SARC Suite composes three independently developed Apache 2.0 pre-action gates at a single control point:
1. **sarc-governance** (authority/permissions gate)
2. **Greensarc** (resource budgets gate: cost + carbon)
3. **sarc-dq** (evidence quality gate)

Each gate has its own:
- Response space (admit, substitute, degrade, escalate, block)
- State management (policies, budgets, governed buffer)
- Evaluation semantics

The composition question is: what verdict should the plane return when gates disagree, and in what order should they run when one (evidence gate) can rewrite the action?

## Decision

We implement **min semantics** with a **two-phase protocol**:

### Min Semantics (Non-Compensatory Join)
- Order responses by restrictiveness: admit < substitute < degrade < escalate < block
- Composed verdict = max(responses), the most restrictive
- Rationale: Proposition 1 shows compensatory aggregation (avg, weighted sum) admits actions vetoed by a member gate; min (ordinal form: max by restrictiveness) preserves veto

### Two-Phase Protocol
1. **Phase I**: Evaluate evidence gate
   - If response is SUBSTITUTE: recompute action context with substituted value
   - If response is ADMIT/DEGRADE/ESCALATE/BLOCK: proceed to Phase II with original context

2. **Phase II**: Evaluate all gates on the remediated action
   - Return join of Phase II responses
   - Record both phases in the Evidence Set

### Rationale
- **Single-pass unsoundness** (Proposition 3): evaluating all gates on the original action leaves the authority and resource gates judging values that will not be executed (if DQ substitutes)
- **Termination** (Lemma 1): DQ substitution is idempotent; the remediated action uses only governed records that DQ admits by construction, so no further remediation
- **Soundness** (Theorem 1): Phase II evaluates every gate on the executed action itself; the join preserves every Held verdict

## API Mapping

### sarc-governance
- **Import**: `from sarc_governance import ConstraintSpec, load_spec`
- **Used for**: Authority gate (role_authorised, order_value_cap constraints)
- **Response mapping**: constraint violation → Response.BLOCK or Response.ESCALATE
- **State**: Constraint spec loaded from YAML

### sarc-dq
- **Import**: `from sarc_dq import EvidenceRecord, PreActionGate`
- **Used for**: Evidence quality gate (defect detection + remediation)
- **Response mapping**: DQ predicate result → Response.{ADMIT, SUBSTITUTE, BLOCK, ESCALATE}
- **State**: Governed buffer (verified records for substitution)
- **Spec**: Load via `sarc_dq.dq_spec.load_spec()` with gate extra for YAML support

### Greensarc
- **Import**: `from green_sarc import PreActionGate, ColdStartEstimator`
- **Used for**: Resource gate (cost + carbon budgets)
- **Response mapping**: budget violation → Response.ESCALATE or Response.BLOCK
- **Estimator**: ColdStartEstimator (zero-history forecast)
- **State**: Daily cost and carbon budgets

## Unified Evidence Set Structure

One JSON line per decision containing:
```json
{
  "day": <int>,
  "sku": <str>,
  "context": {
    "agent_id": <str>,
    "role": <str>,
    "proposed_qty": <float>,
    "order_value": <float>,
    "est_cost_eur": <float>,
    "est_carbon_g": <float>
  },
  "phase1": {
    "dq_response": <str>,
    "substituted_value": <float or null>
  },
  "gates": {
    "sarc": {
      "constraints_evaluated": {...},
      "verdict": <str>
    },
    "green": {
      "predicted_cost": <float>,
      "predicted_carbon": <float>,
      "budget_state": {...},
      "verdict": <str>
    },
    "dq": {
      "predicates": <str or null>,
      "verdict": <str>,
      "substituted_value": <float or null>,
      "evidence_ids": [<str>, ...]
    }
  },
  "final": {
    "admitted": <bool>,
    "response": <str>,
    "winner_gate": <str>,
    "mode": <"two_phase" or "single_pass">
  },
  "action": {
    "order_qty": <float>,
    "order_value": <float>
  }
}
```

No ground-truth labels in Evidence Sets (they go to run_log.jsonl only).

## Defect Classes (Appendix B Recipes)

Seven defect classes injected deterministically:

1. **stale_master_data**: as_of_day 45-150 days behind, cost 0.55-0.9x true
   - Fires: freshness violation
   - Remediation: substitute from governed buffer

2. **superseded_golden_record**: same record_id, versions v2 and v1, differing cost
   - Fires: version mismatch
   - Remediation: substitute

3. **cross_source_contradiction**: same record_id, different source, >2% cost divergence
   - Fires: source contradiction
   - Response: escalate (no substitute)

4. **schema_drift**: unit_cost as string instead of number
   - Fires: type error
   - Response: block

5. **missing_mandatory_field**: currency field absent
   - Fires: mandatory field missing
   - Response: block

6. **lineage_missing**: metadata.source = ""
   - Fires: PAA flag only (never gates)
   - Response: admit (post-action audit flag)

7. **plausible_outlier**: unit_cost x 2.5, clean fresh metadata and lineage
   - Declared uncovered: no gate detects
   - Response: admit
   - Rationale: tests CH4 (no manufactured coverage)

## Scenarios

### S1: Baseline (Loose budgets, all roles authorised)
- Expected: DQ behaviour dominates; zero sarc/green vetoes
- Tests basic composition

### S2: Tight-budget day
- Budgets sized to trigger green vetoes
- Tests green gate interaction

### S3: Unauthorised burst
- 5% unauthorized role, low order_value_cap
- Tests sarc gate on clean evidence

### S4: Constructive counterexample
- Authority cap strictly between pre- and post-substitution order values
- Run two_phase and single_pass; diff verdicts
- Tests CH2 (single-pass unsoundness)

## Assumptions & Limitations

### Assumptions
- Deterministic gates only (no model calls)
- Evidence substitution idempotent
- Governed buffer contains only records admitted by evidence gate
- Per-action soundness (stream-level budget coupling out of scope)

### Limitations
- Cold-start estimator for Greensarc (no historical data)
- Synthetic metadata layer (not live data)
- No prevalence claims (mechanism demo, not benchmark)
- Declared-uncovered class (plausible_outlier) remains uncovered

## Testing

11-test suite validates:
1. Clean/auth/budget → admit, winner=none
2. Stale record → substitute, admitted, phase1 recorded
3. Schema drift → block, winner=dq
4. Unauthorised → held, winner=sarc
5. Over-budget → vetoed, winner=green
6. Dirty + over-budget → most restrictive wins
7. Determinism: same seed, identical metrics
8. One Evidence Set per decision, no ground_truth in sets, data unchanged
9. S4: divergences exist, two_phase audits clean
10. CH1: audit zero violations across S1-S4
11. Paper pipeline: v0.1 verbatim, v0.2 zero unfilled slots

## Alternatives Considered

1. **Compensatory aggregation** (weighted sum, average): Rejected (Proposition 1: admits vetoed actions)
2. **Single-pass evaluation**: Rejected for soundness (Proposition 3, S4 demonstrates)
3. **Per-gate output without unified Evidence Set**: Rejected (loss of cross-gate lineage)
4. **Live gates with model calls**: Rejected (zero API spend requirement, determinism requirement)

## References

- Proposition 1: Non-compensatory aggregation (multi-criteria decision analysis literature)
- Proposition 3: Single-pass unsoundness; S4 construction
- Lemma 1: Idempotence of substitution
- Theorem 1: Soundness of two-phase protocol

## Implementation Notes

- CompositionEngine class in composition.py
- RetailSimulation in suite_sim.py
- Runner orchestrates S1-S4, both modes
- paper_tables.py generates metrics for paper
- Tests in test_suite_sim.py

## Decision Drivers

1. **Soundness**: Two-phase respects veto (Theorem 1)
2. **Determinism**: Reproducible runs, zero API spend
3. **Lineage**: Unified Evidence Set preserves all cross-gate information
4. **Honesty**: Declared-uncovered class remains uncovered; reported in CH4
5. **Composability**: Unmodified engines (git-clean verification)
