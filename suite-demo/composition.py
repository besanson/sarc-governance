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
SARC Suite Composition: Three-gate orchestration with min semantics.

SEED = 26313
"""
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class Response(Enum):
    """Gate response, ordered by restrictiveness."""
    ADMIT = 0
    SUBSTITUTE = 1
    DEGRADE = 2
    ESCALATE = 3
    BLOCK = 4

    def __lt__(self, other):
        if not isinstance(other, Response):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other):
        if not isinstance(other, Response):
            return NotImplemented
        return self.value <= other.value


class Verdict(Enum):
    """Execution class: Exec vs Held."""
    ADMIT = "admit"  # Exec
    SUBSTITUTE = "substitute"  # Exec
    DEGRADE = "degrade"  # Exec
    ESCALATE = "escalate"  # Held
    BLOCK = "block"  # Held


@dataclass
class ActionContext:
    """Context of a proposed action."""
    agent_id: str
    role: str
    sku: str
    day: int
    proposed_qty: float
    order_value: float
    est_cost_eur: float
    est_carbon_g: float


@dataclass
class GateDecisionRecord:
    """One gate's decision on an action."""
    gate: str
    admitted: bool
    response: str  # "admit", "substitute", "degrade", "escalate", "block"
    detected: Optional[str] = None
    substituted_value: Optional[Any] = None
    firing: Optional[Dict[str, Any]] = None
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class EvidenceSetLine:
    """Unified evidence set for one decision (per 3.4)."""
    day: int
    sku: str
    context: Dict[str, Any]
    phase1: Optional[Dict[str, Any]] = None
    gates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    final: Dict[str, Any] = field(default_factory=dict)
    action: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        """Convert to JSON-serializable dict."""
        result = {
            "day": self.day,
            "sku": self.sku,
            "context": self.context,
            "gates": self.gates,
            "final": self.final,
            "action": self.action,
        }
        if self.phase1 is not None:
            result["phase1"] = self.phase1
        return result


def compute_restrictiveness_join(responses: List[Response]) -> Response:
    """Compute min semantics: max(responses) by restrictiveness."""
    if not responses:
        return Response.ADMIT
    return max(responses, key=lambda r: r.value)


def is_executed(response: Response) -> bool:
    """Check if response is Exec (admit, substitute, degrade)."""
    return response in (Response.ADMIT, Response.SUBSTITUTE, Response.DEGRADE)


class CompositionEngine:
    """Orchestrates three-gate composition with two-phase protocol."""

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode

    def evaluate_dq_gate(
        self,
        evidence_records: List[Any],
        governed_buffer: Dict[str, Any],
        context: ActionContext,
    ) -> tuple[Response, Optional[Any], Dict[str, Any]]:
        """
        Evaluate evidence gate (sarc_dq).
        Returns: (response, substituted_value_if_any, firing_dict)
        """
        # Deterministic mock: check for injected defects
        detected = None
        substituted_value = None
        response = Response.ADMIT
        firing = {}

        for record in evidence_records:
            payload = record.get("payload", {})
            metadata = record.get("metadata", {})

            # Check for defects (all deterministic predicates from Appendix B)
            as_of_day = metadata.get("as_of_day", 0)
            retrieved_day = metadata.get("retrieved_day", 0)
            staleness = retrieved_day - as_of_day

            # stale_master_data: as_of_day set 45 to 150 days behind
            if 45 <= staleness <= 150:
                unit_cost = payload.get("unit_cost", 0)
                if 0.55 * unit_cost <= unit_cost <= 0.9 * unit_cost:
                    detected = "stale_master_data"
                    response = Response.SUBSTITUTE
                    firing["freshness_violation"] = staleness
                    # Substitute from buffer (use true cost)
                    substituted_value = governed_buffer.get("true_unit_cost")
                    break

            # schema_drift: unit_cost as string
            if isinstance(payload.get("unit_cost"), str):
                detected = "schema_drift"
                response = Response.BLOCK
                firing["type_error"] = "unit_cost is string"
                break

            # missing_mandatory_field
            if "currency" not in payload:
                detected = "missing_mandatory_field"
                response = Response.BLOCK
                firing["missing_field"] = "currency"
                break

            # cross_source_contradiction
            sources = [r.get("metadata", {}).get("source") for r in evidence_records]
            if len(set(sources)) > 1:
                # Multiple sources - check for inconsistency
                costs = [r.get("payload", {}).get("unit_cost") for r in evidence_records]
                if costs[0] and costs[1]:
                    diff = abs(costs[0] - costs[1]) / max(costs[0], costs[1])
                    if diff > 0.02:
                        detected = "cross_source_contradiction"
                        response = Response.ESCALATE
                        firing["cost_divergence"] = diff
                        break

            # superseded_golden_record: same record_id, different versions
            # (handled by looking at version numbers)
            versions = [r.get("metadata", {}).get("version") for r in evidence_records]
            if len(versions) > 1 and len(set(versions)) > 1:
                detected = "superseded_golden_record"
                response = Response.SUBSTITUTE
                firing["version_mismatch"] = versions
                substituted_value = governed_buffer.get("true_unit_cost")
                break

        return response, substituted_value, {
            "detected": detected,
            "firing": firing,
        }

    def evaluate_sarc_gate(
        self, context: ActionContext, allowed_roles: List[str], order_value_cap: float
    ) -> tuple[Response, Dict[str, Any]]:
        """
        Evaluate authority gate (sarc_governance).
        Returns: (response, firing_dict)
        """
        firing = {"constraints": {}}

        # role_authorised
        if context.role not in allowed_roles:
            firing["constraints"]["role_authorised"] = {"violated": True}
            return Response.BLOCK, firing

        # order_value_cap
        if context.order_value > order_value_cap:
            firing["constraints"]["order_value_cap"] = {
                "value": context.order_value,
                "cap": order_value_cap,
                "violated": True,
            }
            return Response.ESCALATE, firing

        firing["constraints"]["role_authorised"] = {"violated": False}
        firing["constraints"]["order_value_cap"] = {"violated": False}
        return Response.ADMIT, firing

    def evaluate_green_gate(
        self, context: ActionContext, daily_cost_budget: float, daily_carbon_budget: float
    ) -> tuple[Response, Dict[str, Any]]:
        """
        Evaluate resource gate (green_sarc).
        Returns: (response, firing_dict with budget_state)
        """
        firing = {"budget_state": {}}

        cost_ok = context.est_cost_eur <= daily_cost_budget
        carbon_ok = context.est_carbon_g <= daily_carbon_budget

        if not cost_ok or not carbon_ok:
            firing["budget_state"] = {
                "predicted_cost": context.est_cost_eur,
                "cost_budget": daily_cost_budget,
                "cost_ok": cost_ok,
                "predicted_carbon": context.est_carbon_g,
                "carbon_budget": daily_carbon_budget,
                "carbon_ok": carbon_ok,
            }
            if not cost_ok and not carbon_ok:
                return Response.BLOCK, firing
            return Response.ESCALATE, firing

        firing["budget_state"] = {
            "predicted_cost": context.est_cost_eur,
            "cost_budget": daily_cost_budget,
            "cost_ok": cost_ok,
            "predicted_carbon": context.est_carbon_g,
            "carbon_budget": daily_carbon_budget,
            "carbon_ok": carbon_ok,
        }
        return Response.ADMIT, firing

    def two_phase_composition(
        self,
        context: ActionContext,
        evidence_records: List[Any],
        governed_buffer: Dict[str, Any],
        allowed_roles: List[str],
        order_value_cap: float,
        daily_cost_budget: float,
        daily_carbon_budget: float,
    ) -> EvidenceSetLine:
        """
        Two-phase protocol: Phase I evidence gate, Phase II all gates.
        Returns unified Evidence Set line.
        """
        evidence_set = EvidenceSetLine(
            day=context.day,
            sku=context.sku,
            context={
                "agent_id": context.agent_id,
                "role": context.role,
                "sku": context.sku,
                "day": context.day,
                "proposed_qty": context.proposed_qty,
                "order_value": context.order_value,
                "est_cost_eur": context.est_cost_eur,
                "est_carbon_g": context.est_carbon_g,
            },
        )

        # Phase I: evaluate evidence gate
        dq_response, substituted_value, dq_firing = self.evaluate_dq_gate(
            evidence_records, governed_buffer, context
        )

        # If substitution, recompute context
        remediated_context = context
        if dq_response == Response.SUBSTITUTE and substituted_value is not None:
            # Recompute order_value with substituted cost
            remediated_qty = context.proposed_qty  # simplified: qty unchanged
            remediated_order_value = remediated_qty * substituted_value
            remediated_cost_eur = remediated_qty * substituted_value * 1.2  # dummy overhead
            remediated_carbon_g = remediated_qty * 0.5  # dummy carbon
            remediated_context = replace(
                context,
                proposed_qty=remediated_qty,
                order_value=remediated_order_value,
                est_cost_eur=remediated_cost_eur,
                est_carbon_g=remediated_carbon_g,
            )
            evidence_set.phase1 = {
                "dq_response": dq_response.name,
                "substituted_value": substituted_value,
            }

        # Phase II: evaluate all gates on remediated action
        sarc_response, sarc_firing = self.evaluate_sarc_gate(
            remediated_context, allowed_roles, order_value_cap
        )
        green_response, green_firing = self.evaluate_green_gate(
            remediated_context, daily_cost_budget, daily_carbon_budget
        )
        # Re-evaluate DQ gate on remediated context
        dq_response_ii, _, dq_firing_ii = self.evaluate_dq_gate(
            evidence_records, governed_buffer, remediated_context
        )

        # Join: max by restrictiveness
        final_response = compute_restrictiveness_join(
            [dq_response_ii, sarc_response, green_response]
        )

        # Record gates
        evidence_set.gates = {
            "sarc": {
                "constraints_evaluated": sarc_firing.get("constraints", {}),
                "verdict": sarc_response.name,
            },
            "green": {
                "predicted_cost": remediated_context.est_cost_eur,
                "predicted_carbon": remediated_context.est_carbon_g,
                "budget_state": green_firing.get("budget_state", {}),
                "verdict": green_response.name,
            },
            "dq": {
                "predicates": dq_firing.get("detected"),
                "verdict": dq_response_ii.name,
                "substituted_value": (
                    substituted_value if evidence_set.phase1 else None
                ),
                "evidence_ids": [r.get("record_id", "") for r in evidence_records],
            },
        }

        # Final verdict
        evidence_set.final = {
            "admitted": is_executed(final_response),
            "response": final_response.name,
            "winner_gate": self._find_winner_gate(
                dq_response_ii, sarc_response, green_response, final_response
            ),
            "mode": "two_phase",
        }

        # Action taken
        evidence_set.action = {
            "order_qty": remediated_context.proposed_qty,
            "order_value": remediated_context.order_value,
        }

        return evidence_set

    def single_pass_composition(
        self,
        context: ActionContext,
        evidence_records: List[Any],
        governed_buffer: Dict[str, Any],
        allowed_roles: List[str],
        order_value_cap: float,
        daily_cost_budget: float,
        daily_carbon_budget: float,
    ) -> EvidenceSetLine:
        """
        Single-pass protocol (measurement only): all gates on original action once.
        Returns unified Evidence Set line.
        """
        evidence_set = EvidenceSetLine(
            day=context.day,
            sku=context.sku,
            context={
                "agent_id": context.agent_id,
                "role": context.role,
                "sku": context.sku,
                "day": context.day,
                "proposed_qty": context.proposed_qty,
                "order_value": context.order_value,
                "est_cost_eur": context.est_cost_eur,
                "est_carbon_g": context.est_carbon_g,
            },
        )

        # All gates evaluate the ORIGINAL action once
        dq_response, substituted_value, dq_firing = self.evaluate_dq_gate(
            evidence_records, governed_buffer, context
        )
        sarc_response, sarc_firing = self.evaluate_sarc_gate(
            context, allowed_roles, order_value_cap
        )
        green_response, green_firing = self.evaluate_green_gate(
            context, daily_cost_budget, daily_carbon_budget
        )

        # Join
        final_response = compute_restrictiveness_join(
            [dq_response, sarc_response, green_response]
        )

        evidence_set.gates = {
            "sarc": {
                "constraints_evaluated": sarc_firing.get("constraints", {}),
                "verdict": sarc_response.name,
            },
            "green": {
                "predicted_cost": context.est_cost_eur,
                "predicted_carbon": context.est_carbon_g,
                "budget_state": green_firing.get("budget_state", {}),
                "verdict": green_response.name,
            },
            "dq": {
                "predicates": dq_firing.get("detected"),
                "verdict": dq_response.name,
                "substituted_value": substituted_value,
                "evidence_ids": [r.get("record_id", "") for r in evidence_records],
            },
        }

        evidence_set.final = {
            "admitted": is_executed(final_response),
            "response": final_response.name,
            "winner_gate": self._find_winner_gate(
                dq_response, sarc_response, green_response, final_response
            ),
            "mode": "single_pass",
        }

        # Executed action: if DQ substituted, use remediated qty/value
        executed_qty = context.proposed_qty
        executed_value = context.order_value
        if dq_response == Response.SUBSTITUTE and substituted_value is not None:
            executed_qty = context.proposed_qty
            executed_value = context.proposed_qty * substituted_value

        evidence_set.action = {
            "order_qty": executed_qty,
            "order_value": executed_value,
        }

        return evidence_set

    def _find_winner_gate(
        self, dq_resp: Response, sarc_resp: Response, green_resp: Response, final: Response
    ) -> str:
        """Identify which gate produced the final response (min semantics: max by restrictiveness)."""
        if final == dq_resp:
            return "dq"
        if final == sarc_resp:
            return "sarc"
        if final == green_resp:
            return "green"
        return "none" if final == Response.ADMIT else "unknown"
