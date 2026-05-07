"""Trace store protocol and shared helpers."""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from sarc_governance.trace import TraceRecord


# A trace store stores either dicts or TraceRecord instances.
StoredRecord = Union[TraceRecord, Mapping[str, Any]]


@runtime_checkable
class TraceStore(Protocol):
    """Minimal durable trace store protocol.

    Implementations should be append-only from the caller's perspective:
    callers never edit a stored record, they only append new ones.
    """

    def append(self, record: StoredRecord, *, session_id: Optional[str] = None) -> None:
        """Append a record. ``session_id`` may be inferred from the record."""

    def list(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all records, optionally filtered by session id."""

    def iter_records(self, session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """Stream records as dicts. Useful for large stores."""

    def export_jsonl(self, path: Any, *, session_id: Optional[str] = None) -> int:
        """Write every record to *path* as JSON Lines, returning the count."""

    def close(self) -> None:
        """Close the store. Idempotent."""


# ---------------------------------------------------------------------------
# Helpers used by all concrete stores
# ---------------------------------------------------------------------------


def to_dict(record: StoredRecord) -> Dict[str, Any]:
    """Coerce a stored record into a JSON-friendly dict."""
    if isinstance(record, TraceRecord):
        return record.to_dict()
    if isinstance(record, Mapping):
        return dict(record)
    raise TypeError(
        f"trace store: record must be TraceRecord or Mapping; got {type(record).__name__}"
    )


def matches_session(record: Mapping[str, Any], session_id: Optional[str]) -> bool:
    """Return True iff *record* has the supplied session_id (or filter is None)."""
    if session_id is None:
        return True
    sid = record.get("session_id")
    if sid is None:
        # session_id may have been stamped into extra/execution_context.
        extra = record.get("extra", {})
        if isinstance(extra, Mapping):
            ec = extra.get("execution_context")
            if isinstance(ec, Mapping):
                sid = ec.get("session_id")
    return sid == session_id


__all__ = ["StoredRecord", "TraceStore", "to_dict", "matches_session"]
