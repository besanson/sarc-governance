"""Smoke tests for examples/openai_tool_calling_adapter/run_demo.py."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

DEMO = (
    pathlib.Path(__file__).resolve().parent.parent
    / "examples"
    / "openai_tool_calling_adapter"
    / "run_demo.py"
)


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("openai_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


async def test_dispatch_produces_role_tool_messages(demo):
    messages = await demo.run()
    assert len(messages) == 3
    for m in messages:
        assert m["role"] == "tool"
        assert "tool_call_id" in m
        assert "content" in m

    bodies = [json.loads(m["content"]) for m in messages]
    assert bodies[0]["city"] == "Paris"
    assert bodies[1]["status"] == "executed"
    assert bodies[2]["error"] == "blocked_by_governance"
    assert bodies[2]["constraint_id"] == "ch_large_transfer"
    assert bodies[2]["point"] == "PAG"


async def test_invalid_arguments_json_handled(demo):
    governed = demo.GovernanceToolset(
        wrapped=demo.OpenAIFunctionToolset(demo.FUNCTIONS), spec=demo.SPEC
    )
    out = await demo.dispatch_tool_calls(
        governed,
        [
            {
                "id": "call_bad",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": "not json",
                },
            }
        ],
    )
    assert len(out) == 1
    body = json.loads(out[0]["content"])
    assert body["error"] == "invalid_arguments_json"
