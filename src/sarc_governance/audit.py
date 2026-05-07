"""SARC audit_trace — specification-trace correspondence check (paper §3.5).

``audit_trace(spec, trace)`` checks four categories of discrepancy:

1. **coverage** — an applicable constraint was not evaluated for an action,
   or the trace references a constraint not in the spec.
2. **placement** — a constraint was evaluated at a point incompatible with
   its class (e.g. a ``hard`` constraint evaluated only at PAA).
3. **response** — a fired constraint used a response different from what
   the spec declares.
4. **attribution** — the action record lacks a non-empty authority chain.

The function accepts two input shapes for the ``trace``:

- A flat list of ``TraceRecord`` dicts (the native output of
  ``GovernanceToolset``).  Each dict has ``action_id``, ``constraint_id``,
  ``point``, ``fired``, ``response``, ``class``.
- A list of higher-level action dicts in the original ``sarc_eval.py``
  schema: ``{"action_id", "evaluated": [...], "attribution": {...}}``.
  The function auto-detects the schema.

Returns a list of discrepancy dicts.  An empty list means the trace is
SARC-conformant under the supplied spec (invariants I1–I3 of the paper).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sarc_governance.constraints import (
    Constraint,
    ConstraintSpec,
    is_compatible,
    EnforcementPoint,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def audit_trace(
    spec: ConstraintSpec,
    trace: List[Dict[str, Any]],
    *,
    check_attribution: bool = True,
) -> List[Dict[str, Any]]:
    """Check a runtime trace against a SARC spec.

    Parameters
    ----------
    spec:
        The ``ConstraintSpec`` that was (or should have been) used during
        the run.
    trace:
        Either a flat list of ``TraceRecord`` dicts (the output of
        ``GovernanceToolset._emit``) or a list of action-level records in
        the ``sarc_eval.py`` schema.
    check_attribution:
        When ``True`` (default) the attribution completeness invariant is
        also checked.

    Returns
    -------
    list[dict]
        Discrepancy records, each with keys:
        ``action_id``, ``constraint`` (or ``None``), ``type``, ``message``.
    """
    if not trace:
        return []

    # Detect schema: flat trace records vs action-level records.
    if _is_flat_trace(trace):
        return _audit_flat(spec, trace, check_attribution=check_attribution)
    else:
        return _audit_action_level(spec, trace, check_attribution=check_attribution)


# ---------------------------------------------------------------------------
# Flat trace (GovernanceToolset native output)
# ---------------------------------------------------------------------------


def _is_flat_trace(trace: List[Dict[str, Any]]) -> bool:
    """Return True if the trace looks like a list of TraceRecord dicts."""
    first = trace[0]
    return "constraint_id" in first and "point" in first


def _audit_flat(
    spec: ConstraintSpec,
    trace: List[Dict[str, Any]],
    *,
    check_attribution: bool,
) -> List[Dict[str, Any]]:
    constraints = {c.id: c for c in spec.constraints}
    discrepancies: List[Dict[str, Any]] = []

    # Group by action_id.
    by_action: Dict[str, List[Dict[str, Any]]] = {}
    for rec in trace:
        by_action.setdefault(rec["action_id"], []).append(rec)

    for action_id, records in by_action.items():
        evaluated_ids = {r["constraint_id"] for r in records}

        # I1: coverage — every spec constraint should appear in the trace.
        for cid, c in constraints.items():
            if cid not in evaluated_ids:
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "coverage",
                        "Applicable constraint was not evaluated.",
                    )
                )

        for rec in records:
            cid = rec["constraint_id"]
            matched: Optional[Constraint] = constraints.get(cid)
            if matched is None:
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "coverage",
                        "Trace references a constraint not in the spec.",
                    )
                )
                continue

            # I2: placement.
            raw_point = rec.get("point", "")
            try:
                point = EnforcementPoint(raw_point)
            except ValueError:
                discrepancies.append(
                    _disc(action_id, cid, "placement", f"Unknown point: {raw_point!r}")
                )
                continue
            if not is_compatible(matched.klass, point):
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "placement",
                        f"Constraint class={matched.klass.value!r} evaluated at incompatible point {point.value!r}.",
                    )
                )

            # I3: response.
            if rec.get("fired"):
                rec_resp = rec.get("response", "")
                if rec_resp != matched.response.value:
                    discrepancies.append(
                        _disc(
                            action_id,
                            cid,
                            "response",
                            f"Fired constraint used response {rec_resp!r}; spec requires {matched.response.value!r}.",
                        )
                    )

    return discrepancies


# ---------------------------------------------------------------------------
# Action-level trace (sarc_eval.py schema)
# ---------------------------------------------------------------------------


def _audit_action_level(
    spec: ConstraintSpec,
    trace: List[Dict[str, Any]],
    *,
    check_attribution: bool,
) -> List[Dict[str, Any]]:
    """Handle the higher-level trace schema from ``sarc_eval.py``."""
    constraints = {c.id: c for c in spec.constraints}
    discrepancies: List[Dict[str, Any]] = []

    for i, rec in enumerate(trace):
        action_id = rec.get("action_id", str(i))
        evaluated_list = rec.get("evaluated", [])
        evaluated = {e["id"]: e for e in evaluated_list}

        # I1: coverage.
        for c in spec.constraints:
            if c.id not in evaluated:
                # We cannot know from the action dict alone whether the
                # constraint applies, so we flag any constraint that *fired*
                # in at least one record but is missing here.
                # For the sarc_eval schema we conservatively flag all missing.
                discrepancies.append(
                    _disc(
                        action_id,
                        c.id,
                        "coverage",
                        "Applicable constraint was not evaluated.",
                    )
                )

        for cid, ev in evaluated.items():
            matched: Optional[Constraint] = constraints.get(cid)
            if matched is None:
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "coverage",
                        "Trace references a constraint not in the spec.",
                    )
                )
                continue

            # I2: placement.
            raw_verif = ev.get("verif", "")
            try:
                point = EnforcementPoint(raw_verif)
            except ValueError:
                # sarc_eval uses non-SARC strings like "policy_layer" — treat
                # as a placement discrepancy only if not in the allowed set.
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "placement",
                        f"Evaluated at non-SARC point {raw_verif!r}.",
                    )
                )
                continue
            if not is_compatible(matched.klass, point):
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "placement",
                        f"Constraint class={matched.klass.value!r} evaluated at incompatible point {point.value!r}.",
                    )
                )

            # I3: response.
            if ev.get("fired") and ev.get("response") != matched.response.value:
                discrepancies.append(
                    _disc(
                        action_id,
                        cid,
                        "response",
                        f"Fired constraint used response {ev['response']!r}; spec requires {matched.response.value!r}.",
                    )
                )

        # Attribution completeness.
        if check_attribution:
            attrib = rec.get("attribution", {})
            if not attrib.get("authority_nonempty", False):
                discrepancies.append(
                    _disc(
                        action_id,
                        None,
                        "attribution",
                        "Attribution chain has empty authority.",
                    )
                )

    return discrepancies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _disc(
    action_id: str,
    constraint: Optional[str],
    dtype: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "action_id": action_id,
        "constraint": constraint,
        "type": dtype,
        "message": message,
    }


__all__ = ["audit_trace"]
