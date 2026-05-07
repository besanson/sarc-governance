"""Tests for ``ExecutionContext`` and its integration with GovernanceToolset."""

from __future__ import annotations

from dataclasses import dataclass


from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ExecutionContext,
    GovernanceToolset,
)


def test_execution_context_defaults_are_empty():
    ec = ExecutionContext()
    assert ec.is_empty()
    assert ec.principal_id == ""
    assert ec.roles == ()


def test_execution_context_from_mapping_known_fields():
    ec = ExecutionContext.from_mapping(
        {
            "principal_id": "alice",
            "agent_id": "agent-1",
            "session_id": "s1",
            "roles": ["procurement", "approver"],
            "environment": "prod",
        }
    )
    assert ec.principal_id == "alice"
    assert ec.agent_id == "agent-1"
    assert ec.roles == ("procurement", "approver")
    assert ec.environment == "prod"


def test_execution_context_from_mapping_unknown_keys_go_to_metadata():
    ec = ExecutionContext.from_mapping({"principal_id": "bob", "team": "infra"})
    assert ec.principal_id == "bob"
    assert ec.metadata == {"team": "infra"}


def test_execution_context_from_obj_returns_empty_for_none():
    assert ExecutionContext.from_obj(None).is_empty()


def test_execution_context_from_obj_passthrough_when_already_a_context():
    src = ExecutionContext(principal_id="x")
    assert ExecutionContext.from_obj(src) is src


def test_execution_context_from_obj_reads_attached_attribute():
    @dataclass
    class FakeCtx:
        execution_context: ExecutionContext

    fake = FakeCtx(execution_context=ExecutionContext(principal_id="alice"))
    ec = ExecutionContext.from_obj(fake)
    assert ec.principal_id == "alice"


def test_execution_context_to_dict_round_trips():
    ec = ExecutionContext(
        principal_id="p", roles=("a", "b"), metadata={"foo": "bar"}
    )
    d = ec.to_dict()
    assert d["roles"] == ["a", "b"]
    assert d["metadata"] == {"foo": "bar"}


# --- integration with GovernanceToolset ------------------------------------


class _Toolset:
    async def call_tool(self, name, args, ctx, tool):
        return {"ok": True, "name": name}


async def test_governance_toolset_stamps_execution_context_into_trace():
    captured = []

    async def memory_add_event(session_id, event_type, content, metadata=None):
        captured.append(content)

    class _Mem:
        add_event = staticmethod(memory_add_event)

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="cs_log",
                klass="soft",
                verif="PAA",
                response="log",
                predicate=lambda ctx: True,
            )
        ]
    )

    ec = ExecutionContext(principal_id="alice", session_id="s1", environment="prod")
    governed = GovernanceToolset(
        wrapped=_Toolset(),
        spec=spec,
        memory_getter=lambda ctx: _Mem(),
        session_id_getter=lambda ctx: "s1",
        context_getter=lambda ctx: ec,
    )
    await governed.call_tool("noop", {}, ctx=None)
    assert captured, "no trace records emitted"
    last = captured[-1]
    assert last["extra"]["execution_context"]["principal_id"] == "alice"
    assert last["extra"]["execution_context"]["environment"] == "prod"


async def test_governance_toolset_stamp_context_disabled():
    captured = []

    async def memory_add_event(session_id, event_type, content, metadata=None):
        captured.append(content)

    class _Mem:
        add_event = staticmethod(memory_add_event)

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="cs_log",
                klass="soft",
                verif="PAA",
                response="log",
                predicate=lambda ctx: True,
            )
        ]
    )

    ec = ExecutionContext(principal_id="alice", session_id="s1")
    governed = GovernanceToolset(
        wrapped=_Toolset(),
        spec=spec,
        memory_getter=lambda ctx: _Mem(),
        session_id_getter=lambda ctx: "s1",
        context_getter=lambda ctx: ec,
        stamp_context=False,
    )
    await governed.call_tool("noop", {}, ctx=None)
    assert captured
    last = captured[-1]
    extra = last.get("extra", {})
    assert "execution_context" not in extra


async def test_governance_toolset_no_context_does_not_stamp():
    captured = []

    async def memory_add_event(session_id, event_type, content, metadata=None):
        captured.append(content)

    class _Mem:
        add_event = staticmethod(memory_add_event)

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="cs_log",
                klass="soft",
                verif="PAA",
                response="log",
                predicate=lambda ctx: True,
            )
        ]
    )

    governed = GovernanceToolset(
        wrapped=_Toolset(),
        spec=spec,
        memory_getter=lambda ctx: _Mem(),
        session_id_getter=lambda ctx: "s1",
    )
    await governed.call_tool("noop", {}, ctx=None)
    assert captured
    extra = captured[-1].get("extra", {})
    assert "execution_context" not in extra
