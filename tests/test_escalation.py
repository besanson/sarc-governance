"""Tests for escalation.py — EscalationRouter."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pytest

from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response
from sarc_governance.escalation import EscalationRouter
from sarc_governance.trace import TraceRecord


def _rec(cid: str = "c1") -> TraceRecord:
    return TraceRecord(
        action_id="a1",
        tool="t",
        point=EnforcementPoint.PAG,
        constraint_id=cid,
        klass=ConstraintClass.HARD,
        fired=True,
        response=Response.BLOCK,
    )


@pytest.mark.asyncio
async def test_router_calls_custom_handler():
    called: List[TraceRecord] = []

    async def handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        called.append(rec)

    router = EscalationRouter(handler=handler)
    rec = _rec()
    await router.route(rec, {"tool": "t"})
    assert len(called) == 1
    assert called[0].constraint_id == "c1"


@pytest.mark.asyncio
async def test_router_uses_default_handler_when_none(caplog):
    """Default handler must log a WARNING without raising."""
    router = EscalationRouter()
    rec = _rec("ch_default")
    with caplog.at_level(logging.WARNING):
        await router.route(rec, {})
    assert "ch_default" in caplog.text


@pytest.mark.asyncio
async def test_router_suppresses_handler_exception():
    """A handler that raises must not propagate — the router swallows it."""

    async def bad_handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        raise RuntimeError("handler failure")

    router = EscalationRouter(handler=bad_handler)
    # Must NOT raise.
    await router.route(_rec(), {})


@pytest.mark.asyncio
async def test_router_passes_ctx_to_handler():
    received_ctx: list = []

    async def handler(rec: TraceRecord, ctx: Dict[str, Any]) -> None:
        received_ctx.append(dict(ctx))

    router = EscalationRouter(handler=handler)
    await router.route(_rec(), {"tool": "my_tool", "args": {"x": 1}})
    assert received_ctx[0]["tool"] == "my_tool"
