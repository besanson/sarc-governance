"""Tests for specs.py — YAML/JSON spec loading and predicate resolution."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from sarc_governance import load_spec, load_spec_from_string, safe_load_spec
from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response


PROCUREMENT_YAML = textwrap.dedent(
    """\
    constraints:
      - id: ch_high_value_po
        class: hard
        verif: PAG
        response: block_or_escalate
        predicate: is_high_value_po
        description: Block POs >= $50 000

      - id: cs_rolling_spend
        class: soft
        verif: PAA
        response: throttle_log
        predicate: rolling_spend_over_threshold
    """
)


def test_load_spec_from_yaml_string():
    spec = load_spec_from_string(PROCUREMENT_YAML, fmt="yaml")
    assert len(spec) == 2
    c = spec.by_id("ch_high_value_po")
    assert c is not None
    assert c.klass is ConstraintClass.HARD
    assert c.verif is EnforcementPoint.PAG
    assert c.response is Response.BLOCK_OR_ESCALATE
    assert c.description.startswith("Block")


def test_load_spec_from_json_string():
    raw = {
        "constraints": [
            {
                "id": "c1",
                "class": "soft",
                "verif": "PAA",
                "response": "throttle_log",
                "predicate": "rolling_spend_over_threshold",
            }
        ]
    }
    spec = load_spec_from_string(json.dumps(raw), fmt="json")
    assert len(spec) == 1
    assert spec.by_id("c1") is not None


def test_load_spec_from_dict():
    raw = {
        "constraints": [
            {
                "id": "x",
                "class": "escalation",
                "verif": "PAG",
                "response": "escalate",
                "predicate": "is_first_time_supplier",
            }
        ]
    }
    spec = load_spec(raw)
    c = spec.by_id("x")
    assert c.klass is ConstraintClass.ESCALATION


def test_load_spec_from_yaml_file(tmp_path: pathlib.Path):
    yaml_file = tmp_path / "test_spec.yaml"
    yaml_file.write_text(PROCUREMENT_YAML, encoding="utf-8")
    spec = load_spec(yaml_file)
    assert len(spec) == 2


def test_load_spec_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_spec("/nonexistent/path/spec.yaml")


def test_load_spec_unknown_predicate_raises():
    with pytest.raises(ValueError, match="No predicate registered"):
        load_spec_from_string(
            textwrap.dedent("""\
            constraints:
              - id: c1
                class: hard
                verif: PAG
                response: block
                predicate: totally_unknown_predicate_xyzzy
            """),
            fmt="yaml",
        )


def test_load_spec_extra_predicates_override():
    custom_pred_fired: list = []

    def my_pred(ctx):
        custom_pred_fired.append(True)
        return True

    spec = load_spec_from_string(
        textwrap.dedent("""\
        constraints:
          - id: custom
            class: hard
            verif: PAG
            response: block
            predicate: my_custom
        """),
        fmt="yaml",
        extra_predicates={"my_custom": my_pred},
    )
    c = spec.by_id("custom")
    assert c is not None
    c.predicate({})
    assert custom_pred_fired == [True]


def test_load_spec_non_string_predicate_raises():
    """Using a non-string predicate field must be rejected (no eval)."""
    raw = {
        "constraints": [
            {
                "id": "c1",
                "class": "hard",
                "verif": "PAG",
                "response": "block",
                "predicate": 42,  # not a string
            }
        ]
    }
    with pytest.raises(ValueError, match="string name"):
        load_spec(raw)


def test_load_spec_missing_required_field_raises():
    raw = {
        "constraints": [
            {
                "id": "c1",
                "class": "hard",
                # verif is missing
                "response": "block",
                "predicate": "is_high_value_po",
            }
        ]
    }
    with pytest.raises(ValueError, match="verif"):
        load_spec(raw)


def test_load_spec_duplicate_ids_raises():
    """The spec loader must propagate ConstraintSpec duplicate-ID errors."""
    raw = {
        "constraints": [
            {
                "id": "dup",
                "class": "hard",
                "verif": "PAG",
                "response": "block",
                "predicate": "is_high_value_po",
            },
            {
                "id": "dup",
                "class": "soft",
                "verif": "PAA",
                "response": "throttle_log",
                "predicate": "rolling_spend_over_threshold",
            },
        ]
    }
    with pytest.raises(ValueError, match="Duplicate"):
        load_spec(raw)


def test_procurement_spec_predicates_callable():
    spec = load_spec_from_string(PROCUREMENT_YAML, fmt="yaml")
    high_value_c = spec.by_id("ch_high_value_po")
    ctx_match = {"tool": "erp.create_po", "args": {"amount": 75_000}}
    ctx_no = {"tool": "erp.create_po", "args": {"amount": 100}}
    assert high_value_c.predicate(ctx_match) is True
    assert high_value_c.predicate(ctx_no) is False


# ===========================================================================
# safe_load_spec
# ===========================================================================


def test_safe_load_spec_loads_from_file(tmp_path: pathlib.Path):
    """safe_load_spec loads a valid YAML file using only registry predicates."""
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(
        "constraints:\n"
        "  - id: ch1\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    response: block_or_escalate\n"
        "    predicate: is_high_value_po\n"
    )
    spec = safe_load_spec(spec_file)
    assert len(spec) == 1
    assert spec.by_id("ch1") is not None


def test_safe_load_spec_rejects_dict():
    """safe_load_spec must not accept a raw dict."""
    with pytest.raises(TypeError, match="does not accept raw dicts"):
        safe_load_spec({"constraints": []})  # type: ignore[arg-type]


def test_safe_load_spec_unknown_predicate_raises(tmp_path: pathlib.Path):
    """safe_load_spec raises ValueError when a predicate is not in the registry."""
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(
        "constraints:\n"
        "  - id: ch1\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    response: block_or_escalate\n"
        "    predicate: not_a_real_predicate_xyz\n"
    )
    with pytest.raises(ValueError, match="not_a_real_predicate_xyz"):
        safe_load_spec(spec_file)


def test_safe_load_spec_file_not_found():
    with pytest.raises(FileNotFoundError):
        safe_load_spec("/no/such/file.yaml")


def test_safe_load_spec_no_extra_predicates_param(tmp_path: pathlib.Path):
    """safe_load_spec has no extra_predicates parameter — verify at call time."""
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(
        "constraints:\n"
        "  - id: ch1\n"
        "    class: hard\n"
        "    verif: PAG\n"
        "    response: block_or_escalate\n"
        "    predicate: is_high_value_po\n"
    )
    import inspect

    sig = inspect.signature(safe_load_spec)
    assert "extra_predicates" not in sig.parameters
