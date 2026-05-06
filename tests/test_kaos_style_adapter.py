"""Integration tests for the KAOS-style adapter example.

These verify that ``GovernanceToolset`` works correctly against a
KAOS / pydantic-ai-shaped ``RunContext`` (with ``ctx.deps.memory`` and
``ctx.deps.session_id``) without any explicit ``memory_getter`` /
``session_id_getter`` overrides — i.e. that auto-detection works.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

EXAMPLE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "examples"
    / "kaos_style_adapter"
    / "run_demo.py"
)

_MODULE_NAME = "kaos_style_adapter_demo"


def _load_demo_module():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register in sys.modules before exec so dataclasses defined in the module
    # can resolve their own type annotations via cls.__module__.
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_demo_runs_end_to_end():
    demo = _load_demo_module()
    summary = await demo.run()

    # Four scenarios: 3 OK + 1 hard-blocked.
    outcomes = summary["outcomes"]
    assert len(outcomes) == 4
    assert [o["ok"] for o in outcomes] == [True, True, True, False]
    assert outcomes[3]["blocked_by"] == "ch_refund_cap"
    assert outcomes[3]["point"] == "PAG"


@pytest.mark.asyncio
async def test_trace_records_persisted_via_ctx_deps_memory():
    """The whole point: trace records reach ctx.deps.memory automatically."""
    demo = _load_demo_module()
    summary = await demo.run()
    trace = summary["trace"]
    assert trace, "expected at least one governance event on ctx.deps.memory"
    # Every record must have the standard TraceRecord fields.
    for rec in trace:
        for key in ("action_id", "tool", "point", "constraint_id", "fired"):
            assert key in rec, f"trace record missing {key}: {rec}"


@pytest.mark.asyncio
async def test_hard_block_prevents_inner_call():
    demo = _load_demo_module()
    summary = await demo.run()
    # The 4th scenario was hard-blocked at PAG, so the inner toolset must have
    # been called for the other three only.
    assert len(summary["inner_calls"]) == 3
    assert all(c["tool"] != "crm.issue_refund" or c["args"]["amount"] < 1_000
               for c in summary["inner_calls"])


@pytest.mark.asyncio
async def test_audit_only_flags_blocked_action_coverage():
    """Hard-blocked actions cause expected coverage gaps; nothing else."""
    demo = _load_demo_module()
    summary = await demo.run()
    discrepancies = summary["discrepancies"]
    # Every reported discrepancy is on the blocked action and is a coverage gap.
    for d in discrepancies:
        assert d["type"] == "coverage", d
        assert d["action_id"] == "act-4", d


@pytest.mark.asyncio
async def test_soft_paa_constraint_fires_on_mid_refund():
    """The $750 refund must record a fired soft PAA constraint."""
    demo = _load_demo_module()
    summary = await demo.run()
    fired_soft = [
        r for r in summary["trace"]
        if r["constraint_id"] == "cs_refund_audit" and r["fired"]
    ]
    assert fired_soft, "expected soft PAA constraint to fire on the $750 refund"
