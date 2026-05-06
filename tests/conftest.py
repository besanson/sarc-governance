"""Shared fixtures and helpers for the sarc_governance test suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pytest

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    EscalationRouter,
    GovernanceToolset,
    TraceRecord,
)
from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response


# ---------------------------------------------------------------------------
# Minimal in-memory memory backend
# ---------------------------------------------------------------------------


@dataclass
class _Session:
    session_id: str
    events: List[Dict[str, Any]] = field(default_factory=list)


class FakeMemory:
    """Synchronous-compatible fake memory that implements MemoryProtocol."""

    def __init__(self) -> None:
        self._sessions: Dict[str, _Session] = {}

    def create(self, session_id: str) -> None:
        self._sessions[session_id] = _Session(session_id=session_id)

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        sess = self._sessions.get(session_id)
        if sess is None:
            return False
        sess.events.append({"event_type": event_type, "content": content})
        return True

    def governance_records(self, session_id: str) -> List[Dict[str, Any]]:
        sess = self._sessions.get(session_id)
        if sess is None:
            return []
        return [e["content"] for e in sess.events if e["event_type"] == "governance_event"]


# ---------------------------------------------------------------------------
# Minimal stub toolset
# ---------------------------------------------------------------------------


class StubToolset:
    """Records every call; returns a canned result (or raises if result is an Exception)."""

    def __init__(self, result: Any = "ok") -> None:
        self.result = result
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def call_tool(self, name: str, tool_args: Dict[str, Any], ctx: Any, tool: Any) -> Any:
        self.calls.append((name, dict(tool_args)))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def make_governance(
    constraints: List[Constraint],
    stub_result: Any = "ok",
    handler=None,
) -> Tuple[GovernanceToolset, StubToolset, FakeMemory, str]:
    """Build a GovernanceToolset with memory wired in, plus helpers."""
    memory = FakeMemory()
    session_id = "test-session"
    memory.create(session_id)
    inner = StubToolset(result=stub_result)
    spec = ConstraintSpec(constraints=constraints)
    router = EscalationRouter(handler=handler)
    toolset = GovernanceToolset(
        wrapped=inner,
        spec=spec,
        router=router,
        memory_getter=lambda _ctx: memory,
        session_id_getter=lambda _ctx: session_id,
    )
    return toolset, inner, memory, session_id


# ---------------------------------------------------------------------------
# Pre-built constraint helpers
# ---------------------------------------------------------------------------


def hard_pag(pred=None) -> Constraint:
    return Constraint(
        id="ch_test",
        klass=ConstraintClass.HARD,
        verif=EnforcementPoint.PAG,
        response=Response.BLOCK,
        predicate=pred if pred is not None else (lambda _: True),
    )


def soft_paa(pred=None) -> Constraint:
    return Constraint(
        id="cs_test",
        klass=ConstraintClass.SOFT,
        verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG,
        predicate=pred if pred is not None else (lambda _: True),
    )


def escalation_pag(pred=None) -> Constraint:
    return Constraint(
        id="ce_test",
        klass=ConstraintClass.ESCALATION,
        verif=EnforcementPoint.PAG,
        response=Response.ESCALATE,
        predicate=pred if pred is not None else (lambda _: True),
    )


def escalation_paa(pred=None) -> Constraint:
    return Constraint(
        id="ce_paa",
        klass=ConstraintClass.ESCALATION,
        verif=EnforcementPoint.PAA,
        response=Response.ESCALATE,
        predicate=pred if pred is not None else (lambda _: True),
    )
