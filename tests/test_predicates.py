"""Tests for predicates.py — registry and built-in procurement predicates."""

from __future__ import annotations

import pytest

from sarc_kaos.predicates import available, get, register


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


def test_get_builtin_predicate():
    p = get("is_high_value_po")
    assert callable(p)


def test_get_unknown_raises():
    with pytest.raises(KeyError, match="No predicate"):
        get("totally_unknown_xyzzy")


def test_available_includes_builtins():
    names = available()
    assert "is_high_value_po" in names
    assert "rolling_spend_over_threshold" in names
    assert "is_first_time_supplier" in names
    assert "any" in names
    assert "never" in names


def test_register_and_retrieve():
    register("_test_reg", lambda ctx: ctx.get("x") == 99)
    p = get("_test_reg")
    assert p({"x": 99}) is True
    assert p({"x": 0}) is False


def test_register_as_decorator():
    @register("_test_decorator")
    def my_pred(ctx):
        return ctx.get("flag") is True

    p = get("_test_decorator")
    assert p({"flag": True}) is True
    assert p({"flag": False}) is False


# ---------------------------------------------------------------------------
# Built-in procurement predicates
# ---------------------------------------------------------------------------


class TestIsHighValuePO:
    def setup_method(self):
        self.pred = get("is_high_value_po")

    def test_fires_at_threshold(self):
        ctx = {"tool": "erp.create_po", "args": {"amount": 50_000}}
        assert self.pred(ctx) is True

    def test_fires_above_threshold(self):
        ctx = {"tool": "erp.create_po", "args": {"amount": 100_000}}
        assert self.pred(ctx) is True

    def test_does_not_fire_below_threshold(self):
        ctx = {"tool": "erp.create_po", "args": {"amount": 49_999}}
        assert self.pred(ctx) is False

    def test_does_not_fire_for_different_tool(self):
        ctx = {"tool": "erp.get_vendor", "args": {"amount": 100_000}}
        assert self.pred(ctx) is False

    def test_missing_amount_treated_as_zero(self):
        ctx = {"tool": "erp.create_po", "args": {}}
        assert self.pred(ctx) is False


class TestIsFirstTimeSupplier:
    def setup_method(self):
        self.pred = get("is_first_time_supplier")

    def test_fires_when_first_time_in_args(self):
        assert self.pred({"args": {"first_time_supplier": True}}) is True

    def test_does_not_fire_when_false(self):
        assert self.pred({"args": {"first_time_supplier": False}}) is False

    def test_fires_when_first_time_in_result(self):
        assert self.pred({"args": {}, "result": {"first_time_supplier": True}}) is True

    def test_does_not_fire_without_key(self):
        assert self.pred({"args": {}}) is False


class TestRollingSpendOverThreshold:
    def setup_method(self):
        self.pred = get("rolling_spend_over_threshold")

    def test_fires_at_threshold(self):
        assert self.pred({"args": {"rolling_24h_spend": 475_000}}) is True

    def test_fires_when_in_result(self):
        assert self.pred({"args": {}, "result": {"rolling_24h_spend": 500_000}}) is True

    def test_does_not_fire_below_threshold(self):
        assert self.pred({"args": {"rolling_24h_spend": 474_999}}) is False


class TestBuiltinAnyNever:
    def test_any_always_true(self):
        p = get("any")
        assert p({}) is True
        assert p({"tool": "x", "args": {}}) is True

    def test_never_always_false(self):
        p = get("never")
        assert p({}) is False
        assert p({"tool": "x", "args": {}}) is False
