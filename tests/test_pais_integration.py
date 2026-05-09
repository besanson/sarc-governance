"""Integration test for the SARC PAIS adapter.

Runs against whichever PAIS implementation is installed:

Stub (stubs/pais_stub)
    Fast, no external deps, always used in the normal ``pais-stub-integration``
    CI job.  Run locally: ``pytest tests/test_pais_integration.py``

Real upstream (axsaucedo/kaos pydantic-ai-server)
    Proves API compatibility with the actual KAOS package.
    Run locally (after installing real PAIS)::

        SARC_REQUIRE_REAL_PAIS=1 pytest tests/test_pais_integration.py

When ``SARC_REQUIRE_REAL_PAIS=1`` is set the test *fails* (rather than skips)
if real PAIS cannot be imported, or if the installed package is the local stub.
This makes the ``pais-upstream-integration`` CI job fail loudly when the
upstream package is missing or incompatible.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sarc_governance import Constraint, ConstraintSpec, ConstraintViolation
from sarc_governance.adapters.pais import build_governed_toolset

REQUIRE_REAL_PAIS = os.getenv("SARC_REQUIRE_REAL_PAIS") == "1"

# ---------------------------------------------------------------------------
# Import PAIS — try real upstream first, then stub, fail fast if required
# ---------------------------------------------------------------------------
# Real upstream exposes:  pais.memory.LocalMemory
#                         pais.serverutils.AgentDeps
#                         pais.tools.DelegationToolset
#
# Stub exposes:           pais.memory.InMemorySessionStore
#                         pais.context.AgentDeps
#                         pais.tools.DelegationToolset (same name, simpler impl)

try:
    from pais.tools import DelegationToolset as _DelegationToolset  # noqa: F401
    from pais.memory import LocalMemory as _MemoryClass
    from pais.serverutils import AgentDeps as _AgentDepsClass

    _PAIS_IS_REAL = True
except ImportError:
    if REQUIRE_REAL_PAIS:
        # Hard fail: SARC_REQUIRE_REAL_PAIS=1 means the upstream package is required.
        # Do not fall back to the stub — that would be a false green.
        raise
    try:
        from pais.tools import DelegationToolset as _DelegationToolset  # noqa: F401
        from pais.memory import InMemorySessionStore as _MemoryClass  # type: ignore[assignment]
        from pais.context import AgentDeps as _AgentDepsClass  # type: ignore[assignment]

        _PAIS_IS_REAL = False
    except ImportError as exc:
        pytest.skip(f"PAIS not installed: {exc}", allow_module_level=True)
        raise  # unreachable — silences type checker


# ---------------------------------------------------------------------------
# Shared stub toolset (real DelegationToolset requires live HTTP endpoints)
# ---------------------------------------------------------------------------


class _StubToolset:
    """Minimal toolset for integration tests — no network calls needed."""

    async def call_tool(
        self, name: str, tool_args: dict, ctx: Any = None, tool: Any = None
    ) -> str:
        return f"echo: {tool_args.get('task', name)}"


class _Ctx:
    def __init__(self, deps: Any) -> None:
        self.deps = deps


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
async def _pais_env() -> Any:
    """Set up a minimal PAIS environment using whichever package is installed."""
    import pais

    session_id = "integration-test-session"

    if _PAIS_IS_REAL:
        pais_path = str(Path(pais.__file__).resolve())
        # Guard: the upstream job must use the real cloned package, not the stub.
        assert "stubs/pais_stub" not in pais_path, (
            f"SARC_REQUIRE_REAL_PAIS=1 but pais is loaded from the stub at {pais_path!r}. "
            "Install the upstream KAOS package (pydantic-ai-server) instead."
        )

        memory: Any = _MemoryClass()
        await memory.create_session("sarc-integration-test", "test-user", session_id)
        deps = _AgentDepsClass(session_id=session_id, memory=memory)
    else:
        memory = _MemoryClass()  # InMemorySessionStore
        memory.create(session_id)
        deps = _AgentDepsClass(memory=memory, session_id=session_id)

    return _StubToolset(), _Ctx(deps), memory, session_id


# ---------------------------------------------------------------------------
# Helper: retrieve governance events regardless of which PAIS is installed
# ---------------------------------------------------------------------------


async def _governance_events(memory: Any, session_id: str) -> list:
    """Return all governance_event records from the session store."""
    if _PAIS_IS_REAL:
        all_events = await memory.get_session_events(session_id)
        return [e for e in all_events if e.event_type == "governance_event"]
    # Stub path: list_events is synchronous
    try:
        return memory.list_events(session_id, event_type="governance_event")
    except TypeError:
        return [
            e for e in memory.list_events(session_id) if e.get("event_type") == "governance_event"
        ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_allow(_pais_env: Any) -> None:
    """Calls that pass all constraints reach the wrapped toolset and return a result."""
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
    """Calls that fire a hard constraint are blocked with ConstraintViolation."""
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
    """Governance events are written to PAIS session memory."""
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

    events = await _governance_events(memory, session_id)
    assert len(events) >= 1, "Expected at least one governance event in session memory"
