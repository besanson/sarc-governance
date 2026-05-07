"""SARC predicate registry and built-in procurement predicates.

The registry maps string names to callable predicates so that YAML/JSON
specs can reference predicates by name instead of embedding executable code.

Built-in predicates
--------------------
The following names are always available:

Procurement domain
~~~~~~~~~~~~~~~~~~
- ``is_high_value_po``  — tool is ``erp.create_po`` and amount ≥ 50 000
- ``is_first_time_supplier``  — args contain ``first_time_supplier=True``
- ``rolling_spend_over_threshold``  — args/state ``rolling_24h_spend`` ≥ 475 000
- ``result_is_high_value``  — result dict ``amount`` ≥ 50 000
- ``result_has_new_supplier``  — result dict ``new_supplier`` is truthy
- ``any``  — always fires
- ``never``  — never fires

Custom predicates
-----------------
Register your own::

    from sarc_governance.predicates import register

    @register("my_predicate")
    def my_predicate(ctx: dict) -> bool:
        return ctx["args"].get("foo") == "bar"

Or use the functional form::

    register("my_predicate", my_predicate)
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

PredicateFn = Callable[[Dict[str, Any]], bool]

_REGISTRY: Dict[str, PredicateFn] = {}


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


def register(
    name: str,
    fn: Optional[PredicateFn] = None,
) -> PredicateFn | Callable[[PredicateFn], PredicateFn]:
    """Register a named predicate.

    Can be used as a decorator or as a plain call::

        @register("my_pred")
        def my_pred(ctx): ...

        register("my_pred", my_pred)
    """
    if fn is None:

        def decorator(f: PredicateFn) -> PredicateFn:
            _REGISTRY[name] = f
            return f

        return decorator
    _REGISTRY[name] = fn
    return fn


def get(name: str) -> PredicateFn:
    """Return the registered predicate for *name*, raising ``KeyError`` if absent."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No predicate registered under {name!r}. Available: {sorted(_REGISTRY)}"
        ) from None


def available() -> list[str]:
    """Return the sorted list of registered predicate names."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Built-in procurement predicates
# ---------------------------------------------------------------------------


def _is_high_value_po(ctx: Dict[str, Any]) -> bool:
    """Fire when the tool is erp.create_po and the purchase order amount ≥ 50 000."""
    return ctx.get("tool") == "erp.create_po" and ctx.get("args", {}).get("amount", 0) >= 50_000


def _is_first_time_supplier(ctx: Dict[str, Any]) -> bool:
    """Fire when the args or result indicate a first-time supplier."""
    args = ctx.get("args", {})
    result = ctx.get("result", {}) or {}
    return bool(args.get("first_time_supplier")) or bool(
        result.get("first_time_supplier") if isinstance(result, dict) else False
    )


def _rolling_spend_over_threshold(ctx: Dict[str, Any]) -> bool:
    """Fire when rolling 24-hour spend meets or exceeds $475 000."""
    args = ctx.get("args", {})
    result = ctx.get("result") or {}
    spend = args.get("rolling_24h_spend") or (
        result.get("rolling_24h_spend") if isinstance(result, dict) else None
    )
    return (spend or 0) >= 475_000


def _result_is_high_value(ctx: Dict[str, Any]) -> bool:
    """Fire when the tool result contains an ``amount`` ≥ 50 000."""
    result = ctx.get("result") or {}
    if not isinstance(result, dict):
        return False
    return result.get("amount", 0) >= 50_000


def _result_has_new_supplier(ctx: Dict[str, Any]) -> bool:
    """Fire when the tool result indicates a new/first-time supplier."""
    result = ctx.get("result") or {}
    if not isinstance(result, dict):
        return False
    return bool(result.get("new_supplier") or result.get("first_time_supplier"))


def _any(_ctx: Dict[str, Any]) -> bool:
    return True


def _never(_ctx: Dict[str, Any]) -> bool:
    return False


# Register all built-ins.
_BUILTINS: Dict[str, PredicateFn] = {
    "is_high_value_po": _is_high_value_po,
    "is_first_time_supplier": _is_first_time_supplier,
    "rolling_spend_over_threshold": _rolling_spend_over_threshold,
    "result_is_high_value": _result_is_high_value,
    "result_has_new_supplier": _result_has_new_supplier,
    "any": _any,
    "never": _never,
}
_REGISTRY.update(_BUILTINS)


__all__ = [
    "available",
    "get",
    "register",
]
