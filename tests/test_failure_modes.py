"""Failure-mode tests.

Cover the boundary behaviour the README/docs claim:

- Unknown predicate names raise ValueError at spec load.
- Malformed specs raise ValueError.
- A failing escalation handler does not propagate to the agent loop, but
  a hard PAG block still raises (the escalation failure does not turn a
  block into a pass).
- A failing memory backend does not propagate.
"""

from __future__ import annotations

import logging

import pytest

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    EscalationRouter,
    GovernanceToolset,
    load_spec_from_string,
)


# ---------------------------------------------------------------------------
# Spec loader hardening
# ---------------------------------------------------------------------------


def test_unknown_predicate_raises_valueerror():
    yaml_text = (
        "constraints:\n"
        "  - id: ch1\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    response: block\n"
        "    predicate: definitely_not_registered\n"
    )
    with pytest.raises(ValueError):
        load_spec_from_string(yaml_text)


def test_malformed_spec_top_level_raises():
    yaml_text = "constraints: not_a_list\n"
    with pytest.raises(ValueError):
        load_spec_from_string(yaml_text)


def test_constraint_missing_required_key_raises():
    yaml_text = (
        "constraints:\n"
        "  - id: ch1\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    predicate: any\n"  # missing response
    )
    with pytest.raises(ValueError):
        load_spec_from_string(yaml_text)


def test_predicate_must_be_string_not_inline_callable():
    """Inline executable code is rejected — predicates resolve by name."""
    yaml_text = (
        "constraints:\n"
        "  - id: ch1\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    response: block\n"
        "    predicate:\n"
        "      lambda: ctx['x']\n"
    )
    with pytest.raises(ValueError):
        load_spec_from_string(yaml_text)


# ---------------------------------------------------------------------------
# Escalation handler resilience
# ---------------------------------------------------------------------------


class _Toolset:
    async def call_tool(self, name, args, ctx, tool):
        return {"ok": True}


async def test_failing_escalation_handler_does_not_break_agent_loop(caplog):
    async def boom(record, ctx):
        raise RuntimeError("downstream ticket system on fire")

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="ce1",
                klass="escalation",
                verif="PAG",
                response="escalate",
                predicate=lambda ctx: True,
            )
        ]
    )
    governed = GovernanceToolset(
        wrapped=_Toolset(),
        spec=spec,
        router=EscalationRouter(handler=boom),
    )

    with caplog.at_level(logging.ERROR):
        result = await governed.call_tool("noop", {})
    assert result == {"ok": True}
    # The handler exception was logged but suppressed.
    assert any("ER: handler raised" in r.message for r in caplog.records)


async def test_failing_escalation_handler_does_not_silently_pass_a_hard_block(caplog):
    """A failing escalation on a hard PAG must NOT turn the block into a pass."""

    async def boom(record, ctx):
        raise RuntimeError("escalation broken")

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="ch1",
                klass="hard",
                verif="PAG",
                response="block_or_escalate",
                predicate=lambda ctx: True,
            )
        ]
    )
    governed = GovernanceToolset(
        wrapped=_Toolset(),
        spec=spec,
        router=EscalationRouter(handler=boom),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ConstraintViolation):
            await governed.call_tool("dangerous", {})


# ---------------------------------------------------------------------------
# Memory backend resilience
# ---------------------------------------------------------------------------


async def test_failing_memory_does_not_break_agent_loop(caplog):
    class _BrokenMem:
        async def add_event(self, *a, **kw):
            raise RuntimeError("disk full")

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="cs1",
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
        memory_getter=lambda ctx: _BrokenMem(),
        session_id_getter=lambda ctx: "s1",
    )

    with caplog.at_level(logging.ERROR):
        result = await governed.call_tool("noop", {})
    assert result == {"ok": True}
    assert any("failed to persist trace record" in r.message for r in caplog.records)
