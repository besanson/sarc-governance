"""SQLite-backed trace store using the standard library only.

Schema
------
``trace_records (id INTEGER PRIMARY KEY, session_id TEXT, action_id TEXT,
constraint_id TEXT, point TEXT, ts REAL, payload TEXT, prev_hash TEXT,
record_hash TEXT, chain_hash TEXT)``

The ``payload`` column holds the full JSON-serialised record. The other
columns are denormalised for cheap filtering / indexing.

This store is single-writer-friendly. SQLite serialises writers
internally, so multiple processes can append safely as long as they all
go through ``sqlite3`` (and accept its concurrency model).
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import threading
from typing import Any, Dict, Iterator, List, Optional

from sarc_governance.hashchain import GENESIS_PREV_HASH, append_record
from sarc_governance.stores.base import StoredRecord, to_dict


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT,
    action_id     TEXT,
    constraint_id TEXT,
    point         TEXT,
    ts            REAL,
    payload       TEXT NOT NULL,
    prev_hash     TEXT,
    record_hash   TEXT,
    chain_hash    TEXT
);
CREATE INDEX IF NOT EXISTS ix_trace_session ON trace_records(session_id);
CREATE INDEX IF NOT EXISTS ix_trace_action  ON trace_records(action_id);
"""


class SQLiteTraceStore:
    """Single-file SQLite trace store.

    Parameters
    ----------
    path:
        Filesystem path. Use ``":memory:"`` for an ephemeral store.
    hash_chain:
        Opt in to per-record tamper-evident hash chaining. When the store
        is opened on an existing file with chained data, the most recent
        ``chain_hash`` is recovered.

    Thread safety
    -------------
    ``check_same_thread=False`` allows the connection to be shared across
    threads (e.g. an async event loop and a background writer).  A
    ``threading.Lock`` serialises all ``append`` calls so that
    ``_last_chain_hash`` is never read/written concurrently and SQLite
    writes are serialised at the application level as well as the DB level.
    Reads (``list``, ``iter_records``, ``export_jsonl``) are not locked
    because SQLite's WAL mode provides consistent reads; use a single
    ``SQLiteTraceStore`` instance per file.
    """

    def __init__(self, path: Any, *, hash_chain: bool = False) -> None:
        self._path_str = str(path)
        if path != ":memory:":
            pathlib.Path(self._path_str).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path_str, check_same_thread=False)
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._hash_chain = hash_chain
        self._write_lock = threading.Lock()
        self._last_chain_hash = GENESIS_PREV_HASH
        if hash_chain:
            self._last_chain_hash = self._recover_last_hash()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _recover_last_hash(self) -> str:
        cur = self._conn.execute(
            "SELECT chain_hash FROM trace_records WHERE chain_hash IS NOT NULL ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
        return GENESIS_PREV_HASH

    # ------------------------------------------------------------------
    # TraceStore protocol
    # ------------------------------------------------------------------

    def append(self, record: StoredRecord, *, session_id: Optional[str] = None) -> None:
        d = to_dict(record)
        if session_id is not None and "session_id" not in d:
            d["session_id"] = session_id
        with self._write_lock:
            if self._hash_chain:
                d = append_record(d, prev_chain_hash=self._last_chain_hash)
                self._last_chain_hash = d["chain_hash"]
            sid = d.get("session_id")
            if sid is None:
                extra = d.get("extra", {})
                ec = extra.get("execution_context") if isinstance(extra, dict) else None
                if isinstance(ec, dict):
                    sid = ec.get("session_id")
            payload = json.dumps(d, sort_keys=True)
            self._conn.execute(
                """
                INSERT INTO trace_records
                    (session_id, action_id, constraint_id, point, ts, payload,
                     prev_hash, record_hash, chain_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    d.get("action_id"),
                    d.get("constraint_id"),
                    d.get("point"),
                    d.get("timestamp"),
                    payload,
                    d.get("prev_hash"),
                    d.get("record_hash"),
                    d.get("chain_hash"),
                ),
            )
            self._conn.commit()

    def list(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.iter_records(session_id=session_id))

    def iter_records(self, session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        if session_id is None:
            cur = self._conn.execute("SELECT payload FROM trace_records ORDER BY id")
        else:
            cur = self._conn.execute(
                "SELECT payload FROM trace_records WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
        for (payload,) in cur:
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue

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
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            pass

    def __enter__(self) -> "SQLiteTraceStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def last_chain_hash(self) -> str:
        return self._last_chain_hash

    def __len__(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM trace_records")
        return int(cur.fetchone()[0])


__all__ = ["SQLiteTraceStore"]
