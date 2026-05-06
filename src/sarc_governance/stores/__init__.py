"""Durable trace store backends for SARC governance traces.

This package provides three concrete stores plus a shared
:class:`TraceStore` protocol:

- :class:`MemoryTraceStore` — in-process list, useful for tests and demos
- :class:`JSONLTraceStore`  — append-only JSON Lines on local disk
- :class:`SQLiteTraceStore` — single-file SQLite (stdlib ``sqlite3``)

All three accept :class:`sarc_governance.trace.TraceRecord` objects or
plain dicts (as emitted by ``GovernanceToolset``) and round-trip them as
JSON-friendly dicts on read.

Each store implements an *optional* tamper-evident hash chain via
:mod:`sarc_governance.hashchain`. Pass ``hash_chain=True`` at
construction time to opt in.

These stores are designed for *single-process, local* deployments. For
multi-writer durability you want a relational DB or a write-once log;
the protocol here is small enough to layer onto either.
"""

from sarc_governance.stores.base import StoredRecord, TraceStore
from sarc_governance.stores.jsonl import JSONLTraceStore
from sarc_governance.stores.memory import MemoryTraceStore
from sarc_governance.stores.sqlite import SQLiteTraceStore

__all__ = [
    "JSONLTraceStore",
    "MemoryTraceStore",
    "SQLiteTraceStore",
    "StoredRecord",
    "TraceStore",
]
