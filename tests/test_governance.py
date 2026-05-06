"""Tests for governance.py — GovernanceToolset enforcement at PAG/ATM/PAA."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    EscalationRouter,
    GovernanceToolset,
    TraceRecord,
)
from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response

from tests.conftest import (
    FakeMemory,
    StubToolset,
    escalation_paa,
    escalation_pag,
    hard_pag,
    make_governance,
    soft_paa,
)


# ===========================================================================
# PAG — Pre-Action Gate
# ===========================================================================


@pytest.mark.asyncio
async def test_pag_hard_blocks_before_dispatch():
    """A hard PAG constraint that fires must raise and not reach the inner tool."""
    toolset, inner, memory, sid = make_governance([hard_pag(lambda _: True)])
    with pytest.raises(ConstraintViolation) as exc_info:
        await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert exc_info.value.point is EnforcementPoint.PAG
    assert exc_info.value.constraint_id == "ch_test"
    assert inner.calls == [], "Inner tool must not be called when PAG blocks."


@pytest.mark.asyncio
async def test_pag_hard_allows_when_predicate_false():
    """A hard PAG constraint that does NOT fire should pass through."""
    toolset, inner, _, _ = make_governance([hard_pag(lambda _: False)])
    result = await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert result == "ok"
    assert len(inner.calls) == 1


@pytest.mark.asyncio
async def test_pag_hard_predicate_receives_correct_context():
    """Predicate must receive tool name and args at PAG."""
    received: list = []

    def pred(ctx: Dict[str, Any]) -> bool:
        received.append(dict(ctx))
        return False

    toolset, _, _, _ = make_governance([
        Constraint(
            id="c",
            klass=ConstraintClass.HARD,
            verif=EnforcementPoint.PAG,
            response=Response.BLOCK,
            predicate=pred,
        )
    ])
    await toolset.call_tool("my_tool", {"x": 1}, ctx=None, tool=None)
    assert received[0]["tool"] == "my_tool"
    assert received[0]["args"] == {"x": 1}


@pytest.mark.asyncio
async def test_pag_hard_block_or_escalate_response_raises():
    """block_or_escalate response at PAG must also raise for hard class."""
    c = Constraint(
        id="c",
        klass=ConstraintClass.HARD,
        verif=EnforcementPoint.PAG,
        response=Response.BLOCK_OR_ESCALATE,
        predicate=lambda _: True,
    )
    toolset, inner, _, _ = make_governance([c])
    with pytest.raises(ConstraintViolation):
        await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert inner.calls == []


@pytest.mark.asyncio
async def test_pag_escalation_routes_then_raises():
    """A fired escalation constraint at PAG must route AND then raise."""
    routed: List[TraceRecord] = []

    async def handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        routed.append(rec)

    c = Constraint(
        id="ce",
        klass=ConstraintClass.ESCALATION,
        verif=EnforcementPoint.PAG,
        response=Response.SUSPEND_ROUTE_DEFAULT_DENY,
        predicate=lambda _: True,
    )
    toolset, inner, _, _ = make_governance([c], handler=handler)
    with pytest.raises(ConstraintViolation):
        await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert len(routed) == 1
    assert routed[0].constraint_id == "ce"
    assert inner.calls == []


@pytest.mark.asyncio
async def test_pag_escalation_fires_router_on_non_blocking_response():
    """An escalation constraint whose response is 'escalate' only routes (no block)."""
    routed: List[TraceRecord] = []

    async def handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        routed.append(rec)

    c = Constraint(
        id="ce",
        klass=ConstraintClass.ESCALATION,
        verif=EnforcementPoint.PAG,
        response=Response.ESCALATE,  # not block_or_escalate
        predicate=lambda _: True,
    )
    toolset, inner, _, _ = make_governance([c], handler=handler)
    # Should NOT raise; escalation is routed but execution continues
    result = await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert result == "ok"
    assert len(routed) == 1
    assert len(inner.calls) == 1


# ===========================================================================
# ATM — Action-Time Monitor
# ===========================================================================


@pytest.mark.asyncio
async def test_atm_hard_raises_after_call():
    """A hard ATM constraint that fires must raise ConstraintViolation (result is lost)."""
    c = Constraint(
        id="ch_atm",
        klass=ConstraintClass.HARD,
        verif=EnforcementPoint.ATM,
        response=Response.BLOCK,
        predicate=lambda ctx: ctx["result"] == "forbidden",
    )
    inner = StubToolset(result="forbidden")
    memory = FakeMemory()
    sid = "s"
    memory.create(sid)
    toolset = GovernanceToolset(
        wrapped=inner,
        spec=ConstraintSpec(constraints=[c]),
        memory_getter=lambda _: memory,
        session_id_getter=lambda _: sid,
    )
    with pytest.raises(ConstraintViolation) as exc_info:
        await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert exc_info.value.point is EnforcementPoint.ATM
    assert len(inner.calls) == 1  # inner was called


@pytest.mark.asyncio
async def test_atm_predicate_receives_elapsed():
    """ATM predicate context must include 'elapsed'."""
    received: list = []

    def pred(ctx: Dict[str, Any]) -> bool:
        received.append(dict(ctx))
        return False

    c = Constraint(
        id="ch_atm",
        klass=ConstraintClass.HARD,
        verif=EnforcementPoint.ATM,
        response=Response.BLOCK,
        predicate=pred,
    )
    toolset, _, _, _ = make_governance([c])
    await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert "elapsed" in received[0]
    assert isinstance(received[0]["elapsed"], float)


# ===========================================================================
# PAA — Post-Action Auditor
# ===========================================================================


@pytest.mark.asyncio
async def test_paa_soft_fires_without_blocking():
    """A fired soft PAA constraint must NOT raise; the call returns normally."""
    toolset, inner, _, _ = make_governance([soft_paa(lambda _: True)])
    result = await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert result == "ok"
    assert len(inner.calls) == 1


@pytest.mark.asyncio
async def test_paa_soft_does_not_route_to_escalation():
    """Soft constraints do not invoke the escalation handler."""
    routed: List[TraceRecord] = []

    async def handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        routed.append(rec)

    toolset, _, _, _ = make_governance([soft_paa(lambda _: True)], handler=handler)
    await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert routed == []


@pytest.mark.asyncio
async def test_paa_escalation_routes_handler():
    """A fired escalation constraint at PAA must invoke the escalation handler."""
    routed: List[TraceRecord] = []

    async def handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        routed.append(rec)

    toolset, _, _, _ = make_governance([escalation_paa(lambda _: True)], handler=handler)
    result = await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert result == "ok"
    assert len(routed) == 1
    assert routed[0].point is EnforcementPoint.PAA
    assert routed[0].fired is True


@pytest.mark.asyncio
async def test_paa_predicate_receives_result():
    """PAA predicate context must include 'result'."""
    received: list = []

    def pred(ctx: Dict[str, Any]) -> bool:
        received.append(dict(ctx))
        return False

    c = Constraint(
        id="cs",
        klass=ConstraintClass.SOFT,
        verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG,
        predicate=pred,
    )
    inner = StubToolset(result={"spend": 500_000})
    toolset = GovernanceToolset(wrapped=inner, spec=ConstraintSpec(constraints=[c]))
    await toolset.call_tool("check_spend", {}, ctx=None, tool=None)
    assert received[0]["result"] == {"spend": 500_000}


# ===========================================================================
# Memory persistence
# ===========================================================================


@pytest.mark.asyncio
async def test_trace_records_written_to_memory():
    """Both the PAG and PAA evaluations must appear in memory."""
    hard = Constraint(
        id="ch",
        klass=ConstraintClass.HARD,
        verif=EnforcementPoint.PAG,
        response=Response.BLOCK,
        predicate=lambda _: False,  # does not fire — let the call through
    )
    soft = Constraint(
        id="cs",
        klass=ConstraintClass.SOFT,
        verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG,
        predicate=lambda _: True,  # fires
    )
    toolset, _, memory, sid = make_governance([hard, soft])
    await toolset.call_tool("noop", {}, ctx=None, tool=None)

    records = memory.governance_records(sid)
    points = sorted(r["point"] for r in records)
    assert points == ["PAA", "PAG"]
    fired_ids = {r["constraint_id"] for r in records if r["fired"]}
    assert fired_ids == {"cs"}


@pytest.mark.asyncio
async def test_action_id_increments_per_call():
    toolset, _, memory, sid = make_governance([hard_pag(lambda _: False)])
    await toolset.call_tool("t", {}, ctx=None, tool=None)
    await toolset.call_tool("t", {}, ctx=None, tool=None)
    records = memory.governance_records(sid)
    ids = {r["action_id"] for r in records}
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_no_memory_does_not_raise():
    """When no memory is configured the toolset must still enforce constraints."""
    hard = hard_pag(lambda _: False)
    inner = StubToolset()
    toolset = GovernanceToolset(wrapped=inner, spec=ConstraintSpec(constraints=[hard]))
    result = await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert result == "ok"


# ===========================================================================
# Inner toolset exception propagation
# ===========================================================================


@pytest.mark.asyncio
async def test_inner_exception_propagates_without_paa():
    """If the inner toolset raises, the exception must propagate; PAA must not run."""
    paa_ran: list = []

    soft = Constraint(
        id="cs",
        klass=ConstraintClass.SOFT,
        verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG,
        predicate=lambda _: paa_ran.append(True) or True,
    )
    toolset, _, _, _ = make_governance([soft], stub_result=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await toolset.call_tool("t", {}, ctx=None, tool=None)
    assert paa_ran == [], "PAA must not run when inner tool raises."
