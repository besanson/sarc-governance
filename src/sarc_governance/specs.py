"""SARC spec loader — YAML/JSON → ``ConstraintSpec``.

Loads a constraint specification from a YAML or JSON file (or a raw dict)
and resolves predicate references via the named predicate registry in
``sarc_governance.predicates``.

**Security**: No ``eval`` or ``exec`` is used.  Predicates are resolved by
name through the registry only.  Any attempt to embed executable code in
the YAML will raise a ``ValueError``.

YAML schema
-----------
::

    constraints:
      - id: ch_high_value_po
        class: hard
        verif: PAG
        response: block_or_escalate
        predicate: is_high_value_po           # name in predicates registry
        description: Block POs ≥ $50 000

      - id: cs_rolling_spend
        class: soft
        verif: PAA
        response: throttle_log
        predicate: rolling_spend_over_threshold
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Dict, List, Optional, Union

from sarc_governance.constraints import Constraint, ConstraintSpec
from sarc_governance.predicates import get as get_predicate


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_spec(
    source: Union[str, pathlib.Path, Dict[str, Any]],
    *,
    extra_predicates: Optional[Dict[str, Callable[[Dict[str, Any]], bool]]] = None,
) -> ConstraintSpec:
    """Load a ``ConstraintSpec`` from a YAML file, JSON file, or plain dict.

    Parameters
    ----------
    source:
        Path to a ``.yaml`` / ``.yml`` / ``.json`` file, or a plain dict
        that already matches the spec schema.
    extra_predicates:
        Additional ``{name: callable}`` predicates available for this load
        only (not persisted in the global registry).  Useful in tests.

    Returns
    -------
    ConstraintSpec
        Validated spec with all predicates resolved.

    Raises
    ------
    FileNotFoundError:
        If a path is given that does not exist.
    ValueError:
        If the spec is structurally invalid or a predicate name is unknown.
    """
    if isinstance(source, dict):
        raw = source
    else:
        path = pathlib.Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Spec file not found: {path}")
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            raw = _load_yaml(text)
        elif suffix == ".json":
            raw = json.loads(text)
        else:
            # Try YAML first (superset of JSON).
            raw = _load_yaml(text)

    return _parse(raw, extra_predicates=extra_predicates or {})


def load_spec_from_string(
    text: str,
    *,
    fmt: str = "yaml",
    extra_predicates: Optional[Dict[str, Callable[[Dict[str, Any]], bool]]] = None,
) -> ConstraintSpec:
    """Parse a spec from a YAML or JSON string."""
    if fmt == "json":
        raw = json.loads(text)
    else:
        raw = _load_yaml(text)
    return _parse(raw, extra_predicates=extra_predicates or {})


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_yaml(text: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ModuleNotFoundError as e:
        raise ImportError(
            "pyyaml is required to load YAML specs: pip install pyyaml"
        ) from e
    return yaml.safe_load(text) or {}


def _parse(
    raw: Dict[str, Any],
    *,
    extra_predicates: Dict[str, Callable[[Dict[str, Any]], bool]],
) -> ConstraintSpec:
    raw_constraints: List[Dict[str, Any]] = raw.get("constraints", [])
    if not isinstance(raw_constraints, list):
        raise ValueError(f"'constraints' must be a list; got {type(raw_constraints).__name__}")

    constraints: List[Constraint] = []
    for entry in raw_constraints:
        if not isinstance(entry, dict):
            raise ValueError(f"Each constraint must be a dict; got {type(entry).__name__}")
        constraints.append(_parse_constraint(entry, extra_predicates))

    return ConstraintSpec(constraints=constraints)


def _parse_constraint(
    entry: Dict[str, Any],
    extra_predicates: Dict[str, Callable[[Dict[str, Any]], bool]],
) -> Constraint:
    required = ("id", "class", "verif", "response", "predicate")
    for key in required:
        if key not in entry:
            raise ValueError(f"Constraint entry missing required key {key!r}: {entry}")

    pred_name: str = entry["predicate"]
    if not isinstance(pred_name, str):
        raise ValueError(
            f"'predicate' must be a string name (no eval allowed); got {type(pred_name).__name__}"
        )

    # Resolve: extra_predicates take precedence over global registry.
    if pred_name in extra_predicates:
        predicate = extra_predicates[pred_name]
    else:
        try:
            predicate = get_predicate(pred_name)
        except KeyError as e:
            raise ValueError(str(e)) from e

    return Constraint(
        id=entry["id"],
        klass=entry["class"],
        verif=entry["verif"],
        response=entry["response"],
        predicate=predicate,
        description=entry.get("description", ""),
    )


__all__ = [
    "load_spec",
    "load_spec_from_string",
]
