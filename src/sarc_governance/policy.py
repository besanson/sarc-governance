"""SARC policy metadata, checksum, and diff.

Adds lifecycle primitives on top of :class:`ConstraintSpec`:

- :class:`PolicyMetadata` — owner, version, approval status, timestamps,
  description. **Approval status is informational** — this module records
  what callers claim, it does not validate signatures or enforce a
  workflow. That is the deploying organisation's job.
- :func:`policy_checksum` — deterministic SHA-256 over the canonical
  shape of a spec (id / class / verif / response / predicate-name /
  description). Stable across runs and unaffected by ordering of fields
  in source YAML.
- :func:`inspect_policy` — produce a structured summary of a spec for
  CLI / docs.
- :func:`diff_policies` — structured diff between two specs, returning
  added / removed / changed entries.

Specs that arrive from disk via :func:`sarc_governance.specs.load_spec`
already have predicate references resolved to callables. The checksum is
computed from the *predicate name* if available
(``predicate.__name__``), so two specs that reference the same registered
predicate produce the same checksum even if the callable objects differ.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from sarc_governance.constraints import Constraint, ConstraintSpec


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


VALID_APPROVAL_STATUSES = ("draft", "in_review", "approved", "deprecated")


@dataclass
class PolicyMetadata:
    """Descriptive metadata for a :class:`ConstraintSpec`.

    None of these fields participate in enforcement. They exist so that a
    deploying organisation can pin a known *version* of a spec to every
    trace record and refuse to load specs that are not in the
    ``approved`` state.

    The :attr:`checksum` is recomputed on demand by :func:`policy_checksum`;
    callers may snapshot it here for distribution-time pinning.
    """

    policy_id: str = ""
    version: str = ""
    owner: str = ""
    description: str = ""
    created_at: str = ""
    approved_by: str = ""
    approval_status: str = "draft"
    checksum: str = ""

    def __post_init__(self) -> None:
        if self.approval_status and self.approval_status not in VALID_APPROVAL_STATUSES:
            raise ValueError(
                f"approval_status must be one of {VALID_APPROVAL_STATUSES}; "
                f"got {self.approval_status!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyBundle:
    """A :class:`ConstraintSpec` paired with :class:`PolicyMetadata`."""

    spec: ConstraintSpec
    metadata: PolicyMetadata = field(default_factory=PolicyMetadata)

    def with_recomputed_checksum(self) -> "PolicyBundle":
        meta = PolicyMetadata(
            **{**self.metadata.to_dict(), "checksum": policy_checksum(self.spec)}
        )
        return PolicyBundle(spec=self.spec, metadata=meta)


# ---------------------------------------------------------------------------
# Canonicalisation, checksum
# ---------------------------------------------------------------------------


def _predicate_name(c: Constraint) -> str:
    """Return a stable string identifier for a constraint's predicate.

    Order of preference:

    1. ``predicate.__qualname__`` if set and not a lambda — used by
       registered named predicates and ordinary functions.
    2. ``predicate.__name__`` if set and not ``<lambda>``.
    3. The literal string ``"<lambda>"`` for anonymous lambdas.

    Anonymous lambdas all collapse to ``"<lambda>"``, which means two
    constraints with different lambda bodies but otherwise identical
    fields hash the same. That is a deliberate choice: predicate
    *identity* in SARC is the registered name, not the closure body.
    Users who want a stronger guarantee should register their predicates
    by name.
    """
    fn = c.predicate
    name = getattr(fn, "__name__", None)
    if isinstance(name, str) and name and name != "<lambda>":
        return name
    return "<lambda>"


def _canonical_constraint(c: Constraint) -> Dict[str, Any]:
    return {
        "id": c.id,
        "class": c.klass.value,
        "verif": c.verif.value,
        "response": c.response.value,
        "predicate": _predicate_name(c),
        "description": c.description or "",
    }


def canonical_spec_dict(spec: ConstraintSpec) -> Dict[str, Any]:
    """Return a deterministic JSON-friendly view of *spec* used for hashing."""
    constraints = [_canonical_constraint(c) for c in spec.constraints]
    constraints.sort(key=lambda d: d["id"])
    return {"constraints": constraints}


def policy_checksum(spec: ConstraintSpec) -> str:
    """Return a SHA-256 hex digest over *spec* in canonical form.

    The digest is stable across YAML/JSON formatting differences as long
    as predicate names and core fields (id/class/verif/response/description)
    are unchanged.
    """
    payload = json.dumps(canonical_spec_dict(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


def inspect_policy(
    spec: ConstraintSpec,
    metadata: Optional[PolicyMetadata] = None,
) -> Dict[str, Any]:
    """Produce a structured summary of *spec*, suitable for CLI/JSON output.

    The summary includes the per-class / per-point counts, every
    constraint's canonical form, and the computed checksum. If
    *metadata* is supplied it is included verbatim.
    """
    by_class: Dict[str, int] = {}
    by_point: Dict[str, int] = {}
    constraints = []
    for c in spec.constraints:
        by_class[c.klass.value] = by_class.get(c.klass.value, 0) + 1
        by_point[c.verif.value] = by_point.get(c.verif.value, 0) + 1
        constraints.append(_canonical_constraint(c))

    summary: Dict[str, Any] = {
        "constraint_count": len(spec.constraints),
        "by_class": dict(sorted(by_class.items())),
        "by_point": dict(sorted(by_point.items())),
        "constraints": constraints,
        "checksum": policy_checksum(spec),
    }
    if metadata is not None:
        summary["metadata"] = metadata.to_dict()
    return summary


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def diff_policies(old: ConstraintSpec, new: ConstraintSpec) -> Dict[str, Any]:
    """Return a structured diff between two specs.

    Output shape::

        {
          "added":   [<canonical_constraint>, ...],
          "removed": [<canonical_constraint>, ...],
          "changed": [
            {"id": str, "before": <canonical>, "after": <canonical>,
             "fields": ["class", "response", ...]},
             ...
          ],
          "unchanged": [<id>, ...],
          "checksum": {"old": "...", "new": "...", "equal": bool},
        }
    """
    old_map = {c.id: _canonical_constraint(c) for c in old.constraints}
    new_map = {c.id: _canonical_constraint(c) for c in new.constraints}

    added_ids = sorted(set(new_map) - set(old_map))
    removed_ids = sorted(set(old_map) - set(new_map))
    common_ids = sorted(set(old_map) & set(new_map))

    changed: List[Dict[str, Any]] = []
    unchanged: List[str] = []
    for cid in common_ids:
        before = old_map[cid]
        after = new_map[cid]
        diff_fields = [k for k in before if before[k] != after[k]]
        if diff_fields:
            changed.append(
                {
                    "id": cid,
                    "before": before,
                    "after": after,
                    "fields": diff_fields,
                }
            )
        else:
            unchanged.append(cid)

    old_sum = policy_checksum(old)
    new_sum = policy_checksum(new)

    return {
        "added": [new_map[i] for i in added_ids],
        "removed": [old_map[i] for i in removed_ids],
        "changed": changed,
        "unchanged": unchanged,
        "checksum": {"old": old_sum, "new": new_sum, "equal": old_sum == new_sum},
    }


__all__ = [
    "PolicyBundle",
    "PolicyMetadata",
    "VALID_APPROVAL_STATUSES",
    "canonical_spec_dict",
    "diff_policies",
    "inspect_policy",
    "policy_checksum",
]
