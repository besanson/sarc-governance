"""Tests for constraints.py — enums, Constraint, ConstraintSpec."""

from __future__ import annotations

import pytest

from sarc_kaos.constraints import (
    Constraint,
    ConstraintClass,
    ConstraintSpec,
    EnforcementPoint,
    Response,
    allowed_points,
    is_compatible,
)


# ---------------------------------------------------------------------------
# Enum coercion
# ---------------------------------------------------------------------------


def test_constraint_coerces_string_klass():
    c = Constraint(
        id="x",
        klass="hard",  # type: ignore[arg-type]
        verif="PAG",  # type: ignore[arg-type]
        response="block",  # type: ignore[arg-type]
        predicate=lambda _: True,
    )
    assert c.klass is ConstraintClass.HARD
    assert c.verif is EnforcementPoint.PAG
    assert c.response is Response.BLOCK


def test_constraint_accepts_enum_members():
    c = Constraint(
        id="y",
        klass=ConstraintClass.SOFT,
        verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG,
        predicate=lambda _: False,
    )
    assert c.klass is ConstraintClass.SOFT


# ---------------------------------------------------------------------------
# Class-to-point compatibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "klass,verif,should_pass",
    [
        (ConstraintClass.HARD, EnforcementPoint.PAG, True),
        (ConstraintClass.HARD, EnforcementPoint.ATM, True),
        (ConstraintClass.HARD, EnforcementPoint.PAA, False),  # hard cannot be PAA
        (ConstraintClass.SOFT, EnforcementPoint.ATM, True),
        (ConstraintClass.SOFT, EnforcementPoint.PAA, True),
        (ConstraintClass.SOFT, EnforcementPoint.PAG, False),  # soft cannot be PAG
        (ConstraintClass.ESCALATION, EnforcementPoint.PAG, True),
        (ConstraintClass.ESCALATION, EnforcementPoint.PAA, True),
        (ConstraintClass.ESCALATION, EnforcementPoint.ATM, False),  # escalation cannot be ATM
    ],
)
def test_is_compatible(klass, verif, should_pass):
    assert is_compatible(klass, verif) is should_pass


def test_constraint_rejects_incompatible_hard_paa():
    with pytest.raises(ValueError, match="cannot be verified at"):
        Constraint(
            id="bad",
            klass=ConstraintClass.HARD,
            verif=EnforcementPoint.PAA,
            response=Response.BLOCK,
            predicate=lambda _: True,
        )


def test_constraint_rejects_incompatible_soft_pag():
    with pytest.raises(ValueError, match="cannot be verified at"):
        Constraint(
            id="bad",
            klass=ConstraintClass.SOFT,
            verif=EnforcementPoint.PAG,
            response=Response.THROTTLE_LOG,
            predicate=lambda _: True,
        )


def test_constraint_rejects_incompatible_escalation_atm():
    with pytest.raises(ValueError, match="cannot be verified at"):
        Constraint(
            id="bad",
            klass=ConstraintClass.ESCALATION,
            verif=EnforcementPoint.ATM,
            response=Response.ESCALATE,
            predicate=lambda _: True,
        )


# ---------------------------------------------------------------------------
# ConstraintSpec validation
# ---------------------------------------------------------------------------


def test_spec_rejects_duplicate_ids():
    c1 = Constraint(
        id="dup", klass=ConstraintClass.HARD, verif=EnforcementPoint.PAG,
        response=Response.BLOCK, predicate=lambda _: True,
    )
    c2 = Constraint(
        id="dup", klass=ConstraintClass.SOFT, verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG, predicate=lambda _: True,
    )
    with pytest.raises(ValueError, match="Duplicate"):
        ConstraintSpec(constraints=[c1, c2])


def test_spec_at_filters_by_point():
    c_pag = Constraint(
        id="a", klass=ConstraintClass.HARD, verif=EnforcementPoint.PAG,
        response=Response.BLOCK, predicate=lambda _: True,
    )
    c_paa = Constraint(
        id="b", klass=ConstraintClass.SOFT, verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG, predicate=lambda _: True,
    )
    spec = ConstraintSpec(constraints=[c_pag, c_paa])
    assert spec.at(EnforcementPoint.PAG) == [c_pag]
    assert spec.at(EnforcementPoint.PAA) == [c_paa]
    assert spec.at(EnforcementPoint.ATM) == []


def test_spec_by_id():
    c = Constraint(
        id="find_me", klass=ConstraintClass.HARD, verif=EnforcementPoint.PAG,
        response=Response.BLOCK, predicate=lambda _: True,
    )
    spec = ConstraintSpec(constraints=[c])
    assert spec.by_id("find_me") is c
    assert spec.by_id("absent") is None


def test_spec_len_and_iter():
    c1 = Constraint(
        id="x1", klass=ConstraintClass.HARD, verif=EnforcementPoint.PAG,
        response=Response.BLOCK, predicate=lambda _: True,
    )
    c2 = Constraint(
        id="x2", klass=ConstraintClass.SOFT, verif=EnforcementPoint.PAA,
        response=Response.THROTTLE_LOG, predicate=lambda _: False,
    )
    spec = ConstraintSpec(constraints=[c1, c2])
    assert len(spec) == 2
    assert list(spec) == [c1, c2]


def test_allowed_points():
    assert EnforcementPoint.PAG in allowed_points(ConstraintClass.HARD)
    assert EnforcementPoint.ATM in allowed_points(ConstraintClass.HARD)
    assert EnforcementPoint.PAA not in allowed_points(ConstraintClass.HARD)
