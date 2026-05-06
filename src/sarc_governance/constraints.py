"""SARC constraint model — enums, dataclasses, and validation.

Implements §3.1–§3.3 of the SARC paper:

- ``ConstraintClass``: hard / soft / escalation
- ``EnforcementPoint``: PAG / ATM / PAA / ER
- ``Constraint``: declaration with class, point, response, and predicate
- ``ConstraintSpec``: validated, immutable bundle
- ``PredicateProtocol``: structural typing for callable predicates
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConstraintClass(str, Enum):
    """SARC constraint classes (paper §3.1)."""

    HARD = "hard"
    SOFT = "soft"
    ESCALATION = "escalation"


class EnforcementPoint(str, Enum):
    """SARC enforcement points (paper §4.1)."""

    PAG = "PAG"  # Pre-Action Gate  — before tool dispatch
    ATM = "ATM"  # Action-Time Monitor — around/during dispatch
    PAA = "PAA"  # Post-Action Auditor — after dispatch
    ER = "ER"    # Escalation Router  — asynchronous routing (not an inline point)


class Response(str, Enum):
    """Canonical constraint responses (paper §3.2)."""

    BLOCK = "block"
    BLOCK_OR_ESCALATE = "block_or_escalate"
    THROTTLE_LOG = "throttle_log"
    ESCALATE = "escalate"
    SUSPEND_ROUTE_DEFAULT_DENY = "suspend_route_default_deny"
    LOG = "log"


# ---------------------------------------------------------------------------
# Class-to-point compatibility (paper §4.2, Table 1)
# ---------------------------------------------------------------------------

_CLASS_POINTS: Dict[ConstraintClass, FrozenSet[EnforcementPoint]] = {
    ConstraintClass.HARD: frozenset({EnforcementPoint.PAG, EnforcementPoint.ATM}),
    ConstraintClass.SOFT: frozenset({EnforcementPoint.ATM, EnforcementPoint.PAA}),
    ConstraintClass.ESCALATION: frozenset({EnforcementPoint.PAG, EnforcementPoint.PAA}),
}


def allowed_points(klass: ConstraintClass) -> FrozenSet[EnforcementPoint]:
    """Return the set of enforcement points a constraint class may occupy."""
    return _CLASS_POINTS[klass]


def is_compatible(klass: ConstraintClass, point: EnforcementPoint) -> bool:
    """Return True if *point* is a valid placement for *klass*."""
    allowed = _CLASS_POINTS.get(klass)
    return allowed is not None and point in allowed


# ---------------------------------------------------------------------------
# Predicate Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PredicateProtocol(Protocol):
    """Structural type for constraint predicates.

    A predicate receives a context dict and returns a bool.
    The dict content depends on the enforcement point:

    - PAG: ``{"tool": str, "args": dict}``
    - ATM: ``{"tool": str, "args": dict, "result": Any, "elapsed": float}``
    - PAA: ``{"tool": str, "args": dict, "result": Any}``
    """

    def __call__(self, ctx: Dict[str, Any]) -> bool:  # noqa: D102
        ...


# ---------------------------------------------------------------------------
# Constraint
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Constraint:
    """A SARC constraint declaration (paper §3.1).

    Parameters
    ----------
    id:
        Unique identifier.  Used for trace/audit correlation.
    klass:
        One of ``hard``, ``soft``, or ``escalation`` (as ``ConstraintClass``
        or the raw string value).
    verif:
        The enforcement point (``PAG``, ``ATM``, or ``PAA``).
    response:
        The required response when the predicate fires.
    predicate:
        A callable ``(ctx: dict) -> bool``.  Evaluated at runtime against a
        context dict whose keys depend on the enforcement point.
    description:
        Human-readable description for tooling/docs.
    """

    id: str
    klass: ConstraintClass
    verif: EnforcementPoint
    response: Response
    predicate: Callable[[Dict[str, Any]], bool]
    description: str = ""

    def __post_init__(self) -> None:
        # Coerce string values to enum members so callers can pass raw strings.
        object.__setattr__(self, "klass", ConstraintClass(self.klass))
        object.__setattr__(self, "verif", EnforcementPoint(self.verif))
        object.__setattr__(self, "response", Response(self.response))

        if not is_compatible(self.klass, self.verif):
            allowed = sorted(p.value for p in allowed_points(self.klass))
            raise ValueError(
                f"Constraint {self.id!r}: class={self.klass.value!r} cannot be verified at "
                f"{self.verif.value!r}; allowed points: {allowed}"
            )


# ---------------------------------------------------------------------------
# ConstraintSpec
# ---------------------------------------------------------------------------


@dataclass
class ConstraintSpec:
    """An immutable, validated bundle of constraints (paper §3.3).

    Duplicate constraint IDs are rejected at construction time.
    """

    constraints: List[Constraint] = field(default_factory=list)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for c in self.constraints:
            if c.id in seen:
                raise ValueError(f"Duplicate constraint id in spec: {c.id!r}")
            seen.add(c.id)

    def at(self, point: EnforcementPoint | str) -> List[Constraint]:
        """Return constraints whose verification point matches *point*."""
        p = EnforcementPoint(point)
        return [c for c in self.constraints if c.verif == p]

    def by_id(self, cid: str) -> Optional[Constraint]:
        """Look up a constraint by id, returning None if absent."""
        for c in self.constraints:
            if c.id == cid:
                return c
        return None

    def __len__(self) -> int:
        return len(self.constraints)

    def __iter__(self):
        return iter(self.constraints)


__all__ = [
    "Constraint",
    "ConstraintClass",
    "ConstraintSpec",
    "EnforcementPoint",
    "PredicateProtocol",
    "Response",
    "allowed_points",
    "is_compatible",
]
