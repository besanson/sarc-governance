"""Tamper-evident hash chain over governance trace records.

This module provides a small, dependency-free utility for binding a
sequence of trace records into a SHA-256 chain. Each record is hashed
together with the previous link's hash; tampering with any record (or
inserting / re-ordering records) invalidates every subsequent link.

This is *tamper-evident*, not *tamper-proof*: anyone with write access
to the storage can recompute the full chain after editing. To get
tamper-proofness you need write-once storage, an external timestamping
authority, or a co-signed receipt — see ``docs/security-model.md``.

Public API
----------
- :func:`canonical_event_hash`  — hash one record (no chain)
- :func:`chain_link`            — combine prev hash + record hash
- :func:`append_record`         — wrap a record with chain metadata
- :func:`verify_chain`          — verify a list of chained records
- :class:`ChainError`           — raised on verification failure with a position
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


GENESIS_PREV_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass
class ChainBreak:
    """Describes a single point at which the chain failed to verify."""

    index: int
    reason: str
    expected: Optional[str] = None
    actual: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "reason": self.reason,
            "expected": self.expected,
            "actual": self.actual,
        }


class ChainError(Exception):
    """Raised by :func:`verify_chain` when ``raise_on_break`` is true."""

    def __init__(self, breaks: List[ChainBreak]):
        self.breaks = breaks
        super().__init__(
            f"hash chain failed at {len(breaks)} position(s): "
            + ", ".join(f"{b.index}:{b.reason}" for b in breaks)
        )


# ---------------------------------------------------------------------------
# Canonicalisation and hashing
# ---------------------------------------------------------------------------


CHAIN_FIELDS = ("prev_hash", "record_hash", "chain_hash")


def _canonical_payload(record: Mapping[str, Any]) -> str:
    """Return canonical JSON for *record* excluding chain-metadata fields.

    Sort keys, no whitespace. Excluding the chain fields means we hash the
    *content* of the record, not the chain-metadata that wraps it.
    """
    body = {k: v for k, v in record.items() if k not in CHAIN_FIELDS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(obj: Any) -> Any:
    # Best-effort: dataclass-style objects with to_dict, enums with .value.
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical_event_hash(record: Mapping[str, Any]) -> str:
    """Return SHA-256 over a canonical JSON serialisation of *record*."""
    return _sha256_hex(_canonical_payload(record))


def chain_link(prev_hash: str, record_hash: str) -> str:
    """Return SHA-256 over (prev_hash || record_hash). Order matters."""
    return _sha256_hex(prev_hash + record_hash)


# ---------------------------------------------------------------------------
# Append / verify
# ---------------------------------------------------------------------------


def append_record(
    record: Mapping[str, Any],
    prev_chain_hash: str = GENESIS_PREV_HASH,
) -> Dict[str, Any]:
    """Return *record* augmented with chain metadata.

    Adds three keys: ``prev_hash``, ``record_hash``, ``chain_hash``. The
    input record is not mutated.
    """
    body = {k: v for k, v in record.items() if k not in CHAIN_FIELDS}
    rh = canonical_event_hash(body)
    ch = chain_link(prev_chain_hash, rh)
    out = dict(body)
    out["prev_hash"] = prev_chain_hash
    out["record_hash"] = rh
    out["chain_hash"] = ch
    return out


def chain_records(
    records: Iterable[Mapping[str, Any]],
    initial_prev: str = GENESIS_PREV_HASH,
) -> List[Dict[str, Any]]:
    """Convenience: chain a sequence of records and return the chained list."""
    out: List[Dict[str, Any]] = []
    prev = initial_prev
    for r in records:
        wrapped = append_record(r, prev_chain_hash=prev)
        out.append(wrapped)
        prev = wrapped["chain_hash"]
    return out


def verify_chain(
    records: Sequence[Mapping[str, Any]],
    initial_prev: str = GENESIS_PREV_HASH,
    *,
    raise_on_break: bool = False,
) -> List[ChainBreak]:
    """Verify a sequence of chained records and return any breaks.

    A "break" can be:

    - ``missing_field`` — a chain field is absent
    - ``record_hash_mismatch`` — payload was tampered with
    - ``chain_hash_mismatch`` — link doesn't match expected ``prev_hash``
    - ``prev_hash_mismatch`` — record's ``prev_hash`` doesn't match the
      previous record's ``chain_hash``

    Returns an empty list iff the chain verifies. If ``raise_on_break`` is
    True, raises :class:`ChainError` instead of returning the list.
    """
    breaks: List[ChainBreak] = []
    prev = initial_prev
    for i, rec in enumerate(records):
        for f in CHAIN_FIELDS:
            if f not in rec:
                breaks.append(ChainBreak(index=i, reason="missing_field", expected=f))
                # Cannot verify further fields without the chain metadata.
                prev = ""  # any subsequent prev_hash check will mismatch
                break
        else:
            expected_rh = canonical_event_hash(rec)
            if rec["record_hash"] != expected_rh:
                breaks.append(
                    ChainBreak(
                        index=i,
                        reason="record_hash_mismatch",
                        expected=expected_rh,
                        actual=rec["record_hash"],
                    )
                )
            if rec["prev_hash"] != prev:
                breaks.append(
                    ChainBreak(
                        index=i,
                        reason="prev_hash_mismatch",
                        expected=prev,
                        actual=rec["prev_hash"],
                    )
                )
            expected_ch = chain_link(rec["prev_hash"], rec["record_hash"])
            if rec["chain_hash"] != expected_ch:
                breaks.append(
                    ChainBreak(
                        index=i,
                        reason="chain_hash_mismatch",
                        expected=expected_ch,
                        actual=rec["chain_hash"],
                    )
                )
            prev = rec["chain_hash"]

    if raise_on_break and breaks:
        raise ChainError(breaks)
    return breaks


__all__ = [
    "CHAIN_FIELDS",
    "ChainBreak",
    "ChainError",
    "GENESIS_PREV_HASH",
    "append_record",
    "canonical_event_hash",
    "chain_link",
    "chain_records",
    "verify_chain",
]
