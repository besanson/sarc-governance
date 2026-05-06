"""In-memory trace store.

A trivial list-backed store, useful for tests and short-lived demos.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Iterator, List, Optional

from sarc_governance.hashchain import GENESIS_PREV_HASH, append_record
from sarc_governance.stores.base import StoredRecord, matches_session, to_dict


class MemoryTraceStore:
    """List-backed trace store. Not thread-safe; not durable."""

    def __init__(self, *, hash_chain: bool = False) -> None:
        self._records: List[Dict[str, Any]] = []
        self._hash_chain = hash_chain
        self._last_chain_hash = GENESIS_PREV_HASH

    def append(self, record: StoredRecord, *, session_id: Optional[str] = None) -> None:
        d = to_dict(record)
        if session_id is not None and "session_id" not in d:
            d["session_id"] = session_id
        if self._hash_chain:
            d = append_record(d, prev_chain_hash=self._last_chain_hash)
            self._last_chain_hash = d["chain_hash"]
        self._records.append(d)

    def list(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r for r in self._records if matches_session(r, session_id)]

    def iter_records(self, session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        for r in self._records:
            if matches_session(r, session_id):
                yield r

    def export_jsonl(self, path: Any, *, session_id: Optional[str] = None) -> int:
        out_path = pathlib.Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with out_path.open("w", encoding="utf-8") as f:
            for r in self.iter_records(session_id=session_id):
                f.write(json.dumps(r, sort_keys=True))
                f.write("\n")
                n += 1
        return n

    def close(self) -> None:
        # No-op.
        pass

    @property
    def last_chain_hash(self) -> str:
        return self._last_chain_hash

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["MemoryTraceStore"]
