"""Integration tests for the procurement agent example."""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List

import pytest

from sarc_kaos import (
    ConstraintViolation,
    GovernanceToolset,
    EscalationRouter,
    TraceRecord,
    load_spec,
    audit_trace,
)

SPEC_PATH = pathlib.Path(__file__).parent.parent / "examples" / "procurement_agent" / "sarc_spec.yaml"


class _SimpleMemory:
    def __init__(self):
        self._events: List[Dict[str, Any]] = []

    async def add_event(self, session_id, event_type, content, metadata=None):
        self._events.append({"event_type": event_type, "content": content})
        return True

    def governance_records(self):
        return [e["content"] for e in self._events if e["event_type"] == "governance_event"]


class _ERPToolset:
    def __init__(self):
        self.calls = []
        self.rolling = 0.0

    async def call_tool(self, name, tool_args, ctx, tool):
        self.calls.append((name, dict(tool_args)))
        if name == "erp.create_po":
            amount = tool_args.get("amount", 0)
            self.rolling += amount
            return {"status": "created", "amount": amount, "rolling_24h_spend": self.rolling}
        return {"status": "ok"}


def _make_toolset(handler=None):
    spec = load_spec(SPEC_PATH)
    memory = _SimpleMemory()
    erp = _ERPToolset()
    router = EscalationRouter(handler=handler)
    toolset = GovernanceToolset(
        wrapped=erp,
        spec=spec,
        router=router,
        memory_getter=lambda _: memory,
        session_id_getter=lambda _: "test-session",
    )
    return toolset, erp, memory, spec


@pytest.mark.asyncio
async def test_small_order_passes():
    toolset, erp, _, _ = _make_toolset()
    result = await toolset.call_tool("erp.create_po", {"amount": 5_000, "first_time_supplier": False}, None, None)
    assert result["status"] == "created"
    assert len(erp.calls) == 1


@pytest.mark.asyncio
async def test_high_value_po_blocked_at_pag():
    toolset, erp, _, _ = _make_toolset()
    with pytest.raises(ConstraintViolation) as exc_info:
        await toolset.call_tool("erp.create_po", {"amount": 75_000, "first_time_supplier": False}, None, None)
    assert exc_info.value.constraint_id == "ch_high_value_po"
    assert erp.calls == []


@pytest.mark.asyncio
async def test_first_time_supplier_blocked_and_routed():
    routed: List[TraceRecord] = []

    async def handler(rec, ctx):
        routed.append(rec)

    toolset, erp, _, _ = _make_toolset(handler=handler)
    with pytest.raises(ConstraintViolation) as exc_info:
        await toolset.call_tool("erp.create_po", {"amount": 10_000, "first_time_supplier": True}, None, None)
    assert exc_info.value.constraint_id == "ce_first_time_supplier"
    assert len(routed) == 1
    assert erp.calls == []


@pytest.mark.asyncio
async def test_rolling_spend_flags_paa():
    """A compliant high-spend order must execute but fire the soft PAA constraint.

    We issue many small orders (each below the $50 000 PAG hard threshold) to
    build up rolling spend past the $475 000 PAA soft threshold.
    """
    toolset, erp, memory, _ = _make_toolset()
    # 10 × $49 000 = $490 000 total — crosses the $475 000 soft threshold
    # without ever hitting the $50 000 PAG hard threshold.
    for _ in range(10):
        await toolset.call_tool("erp.create_po", {"amount": 49_000, "first_time_supplier": False}, None, None)

    # All 10 calls must have gone through.
    assert len(erp.calls) == 10
    # The soft cs_rolling_spend constraint should have fired at least once.
    records = memory.governance_records()
    soft_fired = [r for r in records if r["constraint_id"] == "cs_rolling_spend" and r["fired"]]
    assert len(soft_fired) >= 1


@pytest.mark.asyncio
async def test_audit_trace_is_conformant_after_clean_run():
    toolset, _, memory, spec = _make_toolset()
    await toolset.call_tool("erp.create_po", {"amount": 5_000, "first_time_supplier": False}, None, None)
    trace = memory.governance_records()
    discrepancies = audit_trace(spec, trace)
    assert discrepancies == [], f"Expected no discrepancies, got: {discrepancies}"


@pytest.mark.asyncio
async def test_non_erp_tool_is_not_blocked():
    """Constraints bound to erp.create_po must not fire for other tool names."""
    toolset, erp, _, _ = _make_toolset()
    result = await toolset.call_tool("erp.get_vendor", {"vendor_id": "V-1"}, None, None)
    assert result["status"] == "ok"
    assert len(erp.calls) == 1
