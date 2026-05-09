"""Unit tests for sarc_governance.adapters.pais.

No pais package required — all PAIS objects are stubbed in-process.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from sarc_governance import Constraint, ConstraintSpec, ConstraintViolation, GovernanceToolset
from sarc_governance.adapters.pais import (
    PAISContextMapper,
    PAISMemoryGuard,
    build_governed_toolset,
)
from sarc_governance.context import ExecutionContext


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Deps:
    def __init__(
        self,
        session_id: str = "sess-1",
        tenant_id: str = "",
        roles: tuple = (),
        principal_id: str = "",
        memory: Any = None,
    ) -> None:
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.roles = roles
        self.principal_id = principal_id
        self.memory = memory


class _Ctx:
    def __init__(self, deps: _Deps) -> None:
        self.deps = deps


class _PAISMemory:
    """Simulates PAIS memory: silently drops events for uncreated sessions."""

    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.create_calls: list[str] = []
        self.events: list[tuple] = []

    def create(self, session_id: str) -> None:
        self.sessions.add(session_id)
        self.create_calls.append(session_id)

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if session_id not in self.sessions:
            return False  # PAIS silent drop
        self.events.append((session_id, event_type, content))
        return True


class _StubDelegation:
    async def call_tool(self, name: str, tool_args: Dict[str, Any], ctx: Any, tool: Any) -> str:
        return f"ok:{name}"


# ---------------------------------------------------------------------------
# PAISContextMapper
# ---------------------------------------------------------------------------


def test_context_mapper_stamps_constructor_values() -> None:
    mapper = PAISContextMapper(
        "my-agent",
        tenant_id="t1",
        roles=("admin",),
        environment="staging",
        principal_id="u1",
    )
    ctx = _Ctx(_Deps(session_id="s1"))
    ec = mapper(ctx)
    assert isinstance(ec, ExecutionContext)
    assert ec.agent_id == "my-agent"
    assert ec.tenant_id == "t1"
    assert ec.roles == ("admin",)
    assert ec.environment == "staging"
    assert ec.principal_id == "u1"
    assert ec.session_id == "s1"


def test_context_mapper_falls_back_to_deps_tenant() -> None:
    mapper = PAISContextMapper("agent", tenant_id="")
    deps = _Deps(tenant_id="from-deps")
    ec = mapper(_Ctx(deps))
    assert ec.tenant_id == "from-deps"


def test_context_mapper_falls_back_to_deps_roles() -> None:
    mapper = PAISContextMapper("agent")
    deps = _Deps(roles=("viewer",))
    ec = mapper(_Ctx(deps))
    assert ec.roles == ("viewer",)


def test_context_mapper_constructor_roles_override_deps() -> None:
    mapper = PAISContextMapper("agent", roles=("admin",))
    deps = _Deps(roles=("viewer",))
    ec = mapper(_Ctx(deps))
    assert ec.roles == ("admin",)


def test_context_mapper_no_deps_returns_none() -> None:
    mapper = PAISContextMapper("agent")
    assert mapper(object()) is None


# ---------------------------------------------------------------------------
# PAISMemoryGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_guard_calls_create_before_first_event() -> None:
    inner = _PAISMemory()
    guard = PAISMemoryGuard(inner)

    await guard.add_event("s1", "governance_event", {"x": 1})

    assert "s1" in inner.create_calls
    assert len(inner.events) == 1


@pytest.mark.asyncio
async def test_memory_guard_calls_create_only_once_per_session() -> None:
    inner = _PAISMemory()
    guard = PAISMemoryGuard(inner)

    await guard.add_event("s1", "governance_event", {"x": 1})
    await guard.add_event("s1", "governance_event", {"x": 2})
    await guard.add_event("s1", "governance_event", {"x": 3})

    assert inner.create_calls.count("s1") == 1
    assert len(inner.events) == 3


@pytest.mark.asyncio
async def test_memory_guard_creates_separate_sessions_independently() -> None:
    inner = _PAISMemory()
    guard = PAISMemoryGuard(inner)

    await guard.add_event("s1", "governance_event", {})
    await guard.add_event("s2", "governance_event", {})

    assert set(inner.create_calls) == {"s1", "s2"}
    assert len(inner.events) == 2


@pytest.mark.asyncio
async def test_memory_guard_tolerates_inner_without_create() -> None:
    class _NoCreate:
        async def add_event(self, sid: str, et: str, content: Any, metadata=None) -> bool:
            return True

    guard = PAISMemoryGuard(_NoCreate())
    # Must not raise even though create() does not exist on the inner object.
    await guard.add_event("s1", "governance_event", {})


@pytest.mark.asyncio
async def test_memory_guard_tolerates_create_raising() -> None:
    class _CreateRaises:
        async def add_event(self, sid: str, et: str, content: Any, metadata=None) -> bool:
            return True

        def create(self, sid: str) -> None:
            raise RuntimeError("already exists")

    guard = PAISMemoryGuard(_CreateRaises())
    # create() raises but the guard must swallow it and still call add_event.
    await guard.add_event("s1", "governance_event", {})


# ---------------------------------------------------------------------------
# build_governed_toolset
# ---------------------------------------------------------------------------


def _pass_spec() -> ConstraintSpec:
    return ConstraintSpec(
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


def _block_spec() -> ConstraintSpec:
    return ConstraintSpec(
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


def test_build_returns_governance_toolset() -> None:
    ts = build_governed_toolset(_StubDelegation(), "agent", spec=_pass_spec())
    assert isinstance(ts, GovernanceToolset)


def test_build_requires_exactly_one_spec_source_both_raises() -> None:
    with pytest.raises(ValueError):
        build_governed_toolset(
            _StubDelegation(), "agent", spec=_pass_spec(), spec_path="/tmp/x.yaml"
        )


def test_build_requires_exactly_one_spec_source_neither_raises() -> None:
    with pytest.raises(ValueError):
        build_governed_toolset(_StubDelegation(), "agent")


@pytest.mark.asyncio
async def test_build_passthrough_call() -> None:
    ts = build_governed_toolset(_StubDelegation(), "agent", spec=_pass_spec())
    result = await ts.call_tool("lookup", {})
    assert result == "ok:lookup"


@pytest.mark.asyncio
async def test_build_hard_block() -> None:
    ts = build_governed_toolset(_StubDelegation(), "agent", spec=_block_spec())
    with pytest.raises(ConstraintViolation) as exc_info:
        await ts.call_tool("lookup", {})
    assert exc_info.value.constraint_id == "block_all"


@pytest.mark.asyncio
async def test_build_guard_memory_ensures_session_before_emit() -> None:
    """With guard_memory=True, create() is called before the first governance event."""
    inner_mem = _PAISMemory()
    deps = _Deps(session_id="s1", memory=inner_mem)
    ctx = _Ctx(deps)

    soft_spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="soft_log",
                klass="soft",
                verif="PAA",
                response="throttle_log",
                predicate=lambda _: True,
            )
        ]
    )
    ts = build_governed_toolset(_StubDelegation(), "agent", spec=soft_spec, guard_memory=True)
    await ts.call_tool("any_tool", {}, ctx=ctx)

    assert "s1" in inner_mem.create_calls
    assert len(inner_mem.events) >= 1


@pytest.mark.asyncio
async def test_build_guard_memory_false_skips_create() -> None:
    """With guard_memory=False, create() is never called."""
    inner_mem = _PAISMemory()
    # Manually pre-create so events land; we just want to check create_calls.
    inner_mem.create("s1")
    inner_mem.create_calls.clear()

    deps = _Deps(session_id="s1", memory=inner_mem)
    ctx = _Ctx(deps)

    soft_spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="soft_log",
                klass="soft",
                verif="PAA",
                response="throttle_log",
                predicate=lambda _: True,
            )
        ]
    )
    ts = build_governed_toolset(_StubDelegation(), "agent", spec=soft_spec, guard_memory=False)
    await ts.call_tool("any_tool", {}, ctx=ctx)

    # guard is disabled; GovernanceToolset auto-detects ctx.deps.memory directly
    assert inner_mem.create_calls == []
    assert len(inner_mem.events) >= 1


@pytest.mark.asyncio
async def test_context_stamped_on_trace() -> None:
    """tenant_id and agent_id from the mapper appear on predicate context."""
    received: list = []

    def _capture(ctx: dict) -> bool:
        received.append(dict(ctx))
        return False

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="cap",
                klass="hard",
                verif="PAG",
                response="block_or_escalate",
                predicate=_capture,
            )
        ]
    )
    ts = build_governed_toolset(
        _StubDelegation(),
        "my-agent",
        spec=spec,
        tenant_id="acme",
    )
    ctx = _Ctx(_Deps(session_id="s1"))
    await ts.call_tool("t", {}, ctx=ctx)

    ec = received[0].get("execution_context")
    assert ec is not None
    assert ec.agent_id == "my-agent"
    assert ec.tenant_id == "acme"
