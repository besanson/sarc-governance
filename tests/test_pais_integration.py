"""Optional integration test for real PAIS DelegationToolset.

Skipped automatically when the ``pais`` package is not installed.
Run after installing pais from source or your internal registry:

    pip install -e "path/to/kaos/pais"
    pytest tests/test_pais_integration.py -v

The test verifies that a real DelegationToolset wrapped with
sarc_governance.adapters.pais.build_governed_toolset:

1. Allows calls that pass all constraints.
2. Blocks calls that fire a hard constraint.
3. Persists governance trace records via PAIS session memory.
"""

from __future__ import annotations

from typing import Any

import pytest

# All sarc_governance imports must come before the optional skip so that ruff
# does not flag them as E402. The importorskip call is the early-exit guard.
from sarc_governance import Constraint, ConstraintSpec, ConstraintViolation
from sarc_governance.adapters.pais import build_governed_toolset

pais_tools = pytest.importorskip("pais.tools", reason="pais package not installed")


@pytest.fixture()
def _pais_env() -> Any:
    """Minimal PAIS environment: memory, session, and a single sub-agent."""
    try:
        from pais.memory import InMemorySessionStore
        from pais.context import AgentDeps
    except ImportError:
        pytest.skip("pais memory/context imports unavailable")

    memory = InMemorySessionStore()
    session_id = "integration-test-session"
    memory.create(session_id)

    agent_deps = AgentDeps(memory=memory, session_id=session_id)

    class _EchoAgent:
        name = "echo"

        async def process_message(self, task: str, context: Any) -> str:
            return f"echo: {task}"

    try:
        toolset = pais_tools.DelegationToolset(sub_agents=[_EchoAgent()])
    except Exception as exc:
        pytest.skip(f"Could not construct DelegationToolset: {exc}")

    class _Ctx:
        def __init__(self) -> None:
            self.deps = agent_deps

    return toolset, _Ctx(), memory, session_id


@pytest.mark.asyncio
async def test_integration_allow(_pais_env: Any) -> None:
    toolset, ctx, memory, session_id = _pais_env
    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="pass_all",
                klass="hard",
                verif="PAG",
                response="block_or_escalate",
                predicate=lambda _: False,
            )
        ]
    )
    governed = build_governed_toolset(toolset, "test-agent", spec=spec)
    result = await governed.call_tool("echo", {"task": "hello"}, ctx=ctx)
    assert "echo" in str(result).lower()


@pytest.mark.asyncio
async def test_integration_block(_pais_env: Any) -> None:
    toolset, ctx, memory, session_id = _pais_env
    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="block_all",
                klass="hard",
                verif="PAG",
                response="block_or_escalate",
                predicate=lambda _: True,
            )
        ]
    )
    governed = build_governed_toolset(toolset, "test-agent", spec=spec)
    with pytest.raises(ConstraintViolation) as exc_info:
        await governed.call_tool("echo", {"task": "hello"}, ctx=ctx)
    assert exc_info.value.constraint_id == "block_all"


@pytest.mark.asyncio
async def test_integration_trace_persisted(_pais_env: Any) -> None:
    """Governance events must land in PAIS session memory."""
    toolset, ctx, memory, session_id = _pais_env
    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="soft_always",
                klass="soft",
                verif="PAA",
                response="throttle_log",
                predicate=lambda _: True,
            )
        ]
    )
    governed = build_governed_toolset(toolset, "test-agent", spec=spec)
    await governed.call_tool("echo", {"task": "trace-test"}, ctx=ctx)

    try:
        events = memory.list_events(session_id, event_type="governance_event")
    except TypeError:
        events = [
            e for e in memory.list_events(session_id) if e.get("event_type") == "governance_event"
        ]

    assert len(events) >= 1, "Expected at least one governance event in session memory"
