"""Smoke tests for examples/langgraph_style_adapter/run_demo.py."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

DEMO = (
    pathlib.Path(__file__).resolve().parent.parent
    / "examples"
    / "langgraph_style_adapter"
    / "run_demo.py"
)


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("langgraph_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


async def test_demo_run_produces_expected_messages(demo):
    state = await demo.run()
    assert len(state.messages) == 3
    assert len(state.blocked) == 1

    statuses = [m.status for m in state.messages]
    assert statuses == ["ok", "ok", "blocked"]

    blocked = state.messages[2]
    assert blocked.name == "send_email"
    assert blocked.content["error"] == "blocked_by_governance"
    assert blocked.content["constraint_id"] == "ch_external_email"
    assert blocked.content["point"] == "PAG"


async def test_blocked_call_did_not_reach_inner_toolset(demo):
    """The inner toolset must not see the blocked send_email call."""
    inner = demo.FunctionDispatchToolset(demo.TOOLS)
    governed = demo.GovernanceToolset(wrapped=inner, spec=demo.SPEC)

    state = demo.GraphState(
        pending=[
            demo.ToolCall(
                name="send_email",
                args={"to": "ceo@external.com", "subject": "leak"},
                id="tc-blocked",
            ),
        ]
    )
    state = await demo.make_tools_node(governed)(state)
    assert inner.calls == []
    assert state.messages[0].status == "blocked"
