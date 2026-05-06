"""SARC trace and event dataclasses.

Every enforcement evaluation by ``GovernanceToolset`` produces a
``TraceRecord`` that is persisted on the agent's memory (via
``MemoryProtocol``) and used later by ``audit_trace``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response


@dataclass
class TraceRecord:
    """One enforcement evaluation at a single constraint × point.

    Attributes
    ----------
    action_id:
        Monotonically increasing identifier for the tool invocation that
        triggered this evaluation.
    tool:
        Name of the tool that was (or was about to be) called.
    point:
        The enforcement point at which the constraint was evaluated.
    constraint_id:
        ID of the ``Constraint`` that was evaluated.
    klass:
        Class of that constraint (denormalised for fast audit without spec
        look-up).
    fired:
        Whether the predicate returned ``True``.
    response:
        The response code from the constraint declaration.
    timestamp:
        ``time.time()`` at the moment of evaluation.
    extra:
        Arbitrary key-value pairs for extension (e.g. elapsed, error).
    """

    action_id: str
    tool: str
    point: EnforcementPoint
    constraint_id: str
    klass: ConstraintClass
    fired: bool
    response: Response
    timestamp: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON storage."""
        d: Dict[str, Any] = {
            "action_id": self.action_id,
            "tool": self.tool,
            "point": self.point.value,
            "constraint_id": self.constraint_id,
            "class": self.klass.value,
            "fired": self.fired,
            "response": self.response.value,
            "timestamp": self.timestamp,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceRecord":
        """Deserialise from the dict produced by ``to_dict``."""
        return cls(
            action_id=data["action_id"],
            tool=data["tool"],
            point=EnforcementPoint(data["point"]),
            constraint_id=data["constraint_id"],
            klass=ConstraintClass(data["class"]),
            fired=bool(data["fired"]),
            response=Response(data["response"]),
            timestamp=float(data.get("timestamp", 0.0)),
            extra=dict(data.get("extra", {})),
        )


# ---------------------------------------------------------------------------
# Typed action event (higher-level than TraceRecord)
# ---------------------------------------------------------------------------


@dataclass
class ActionEvent:
    """High-level record of one tool invocation and its governance outcome.

    Useful for building structured audit logs from raw ``TraceRecord`` lists.
    """

    action_id: str
    tool: str
    args: Dict[str, Any]
    records: List[TraceRecord] = field(default_factory=list)
    result: Optional[Any] = None
    blocked: bool = False
    attribution: Dict[str, Any] = field(default_factory=dict)

    @property
    def fired_constraints(self) -> List[str]:
        return [r.constraint_id for r in self.records if r.fired]

    @property
    def evaluated_constraint_ids(self) -> set[str]:
        return {r.constraint_id for r in self.records}


def new_action_id() -> str:
    """Generate a unique action identifier."""
    return f"act-{uuid.uuid4().hex[:12]}"


__all__ = [
    "ActionEvent",
    "TraceRecord",
    "new_action_id",
]
