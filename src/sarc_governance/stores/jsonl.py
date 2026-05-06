"""Append-only JSON Lines trace store on local disk.

Each record is one line of canonical JSON. Reads stream the file
line-by-line. Writes use line-buffered append-mode I/O and flush after
each record so a crash mid-write loses at most the in-flight line.

This is a *single-writer* store — concurrent writers from multiple
processes will interleave bytes. Use a real database if you need multi-
writer durability.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
from typing import Any, Dict, Iterator, List, Optional

from sarc_governance.hashchain import GENESIS_PREV_HASH, append_record
from sarc_governance.stores.base import StoredRecord, matches_session, to_dict


class JSONLTraceStore:
    """Append-only JSONL trace store.

    Parameters
    ----------
    path:
        Filesystem path to the JSONL file. Created (with parents) if absent.
    hash_chain:
        When True, every appended record is wrapped with chain metadata
        via :mod:`sarc_governance.hashchain`. The store reads the existing
        file on init to recover the most recent ``chain_hash``.
    """

    def __init__(self, path: Any, *, hash_chain: bool = False) -> None:
        self._path = pathlib.Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._hash_chain = hash_chain
        self._last_chain_hash = GENESIS_PREV_HASH
        self._fp: Optional[io.TextIOBase] = None
        if hash_chain:
            self._last_chain_hash = self._recover_last_hash()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _recover_last_hash(self) -> str:
        last = GENESIS_PREV_HASH
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ch = rec.get("chain_hash")
                    if isinstance(ch, str):
                        last = ch
        except FileNotFoundError:
            pass
        return last

    def _ensure_open(self) -> io.TextIOBase:
        if self._fp is None or self._fp.closed:
            # Line-buffered append.
            self._fp = self._path.open("a", encoding="utf-8", buffering=1)
        return self._fp

    # ------------------------------------------------------------------
    # TraceStore protocol
    # ------------------------------------------------------------------

    def append(self, record: StoredRecord, *, session_id: Optional[str] = None) -> None:
        d = to_dict(record)
        if session_id is not None and "session_id" not in d:
            d["session_id"] = session_id
        if self._hash_chain:
            d = append_record(d, prev_chain_hash=self._last_chain_hash)
            self._last_chain_hash = d["chain_hash"]
        line = json.dumps(d, sort_keys=True)
        fp = self._ensure_open()
        fp.write(line)
        fp.write("\n")
        fp.flush()
        try:
            os.fsync(fp.fileno())
        except (OSError, AttributeError):
            # Some platforms / file types don't support fsync; not fatal.
            pass

    def list(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.iter_records(session_id=session_id))

    def iter_records(self, session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        # Read from disk so concurrent appenders / process restarts work.
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    # Skip corrupted lines — record but don't fail iteration.
                    continue
                if matches_session(rec, session_id):
                    yield rec

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
        if self._fp is not None and not self._fp.closed:
            try:
                self._fp.flush()
            finally:
                self._fp.close()
            self._fp = None

    def __enter__(self) -> "JSONLTraceStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def last_chain_hash(self) -> str:
        return self._last_chain_hash


__all__ = ["JSONLTraceStore"]
