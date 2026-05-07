# Trace stores

`sarc_governance.stores` ships three trace-store backends with a shared
protocol:

| Store | Backend | Use when |
|---|---|---|
| `MemoryTraceStore` | in-process list | tests, demos, single-process runs |
| `JSONLTraceStore` | append-only `.jsonl` file | local single-writer logging, easy `jq` |
| `SQLiteTraceStore` | single-file SQLite (stdlib `sqlite3`) | richer queries, multi-session retention, durability |

Each implements the same minimal protocol:

```python
class TraceStore(Protocol):
    def append(self, record, *, session_id=None) -> None: ...
    def list(self, session_id=None) -> list[dict]: ...
    def iter_records(self, session_id=None) -> Iterator[dict]: ...
    def export_jsonl(self, path, *, session_id=None) -> int: ...
    def close(self) -> None: ...
```

`record` may be a `TraceRecord` dataclass or a plain dict — the store
normalises to dict on write.

## Wiring a store into `GovernanceToolset`

The toolset writes via the existing `MemoryProtocol`; trace stores are
*not* drop-in replacements for `MemoryProtocol`. The recommended
pattern is a thin adapter that fans events out to both:

```python
from sarc_governance import JSONLTraceStore

class StoreBackedMemory:
    def __init__(self, store):
        self._store = store

    async def add_event(self, session_id, event_type, content, metadata=None):
        if event_type == "governance_event":
            self._store.append(content, session_id=session_id)

memory = StoreBackedMemory(JSONLTraceStore("/var/log/sarc/trace.jsonl"))
```

That keeps the library's `MemoryProtocol` (which is *also* used for
non-governance event types your agent emits) decoupled from the trace
store.

For the simplest single-purpose case, see
[`examples/preproduction_trace_store/`](../examples/preproduction_trace_store/README.md).

## Hash chain

All three stores accept `hash_chain=True` at construction. When enabled:

- Every appended record is wrapped with `prev_hash`, `record_hash`, and
  `chain_hash` fields (see [hashchain.py](../src/sarc_governance/hashchain.py)).
- On reopen, the store recovers the most recent `chain_hash` so the
  chain continues across process restarts.
- `verify_chain(records)` returns the empty list iff the chain still
  verifies.

The hash chain is *tamper-evident*, not *tamper-proof*: anyone with
write access to the storage can recompute the full chain after editing.
For real tamper-proofness pair the chain with write-once storage or an
external timestamping authority. See [`security-model.md`](security-model.md).

## Concurrency

- `MemoryTraceStore` — not thread-safe. Use one per agent loop.
- `JSONLTraceStore` — single-writer. Multiple processes appending to
  the same file will interleave bytes and corrupt lines. Use SQLite if
  you need that.
- `SQLiteTraceStore` — SQLite serialises writers internally. Multiple
  processes can append safely; readers see a consistent view between
  commits.

None of the stores is a substitute for a real durable log (Kafka, S3
append, your data warehouse) for production volumes. Use the
`TraceStore` protocol as the seam to ship a deployment-specific
implementation against.

## Exporting

```bash
# Export a SQLite store to JSONL for ingestion by an external tool.
sarc-governance trace export /var/log/sarc/trace.sqlite trace.jsonl

# Filter to a single session.
sarc-governance trace export /var/log/sarc/trace.sqlite trace.jsonl \
    --session-id sess-2026-05-06-abc

# Verify the chain on the exported file.
sarc-governance trace verify-chain trace.jsonl
```

## Extending to multi-writer backends

The bundled stores are single-process. When you need multiple PAIS pods, a
separate audit service, or a data-warehouse sink, implement `TraceStore` over
your chosen backend. The protocol is five methods:

```python
from sarc_governance.stores import TraceStore   # typing.Protocol
```

### Postgres (psycopg2 / psycopg3)

```python
import json
from typing import Any, Dict, Iterator, List, Optional
import psycopg2

class PostgresTraceStore:
    """Append-only Postgres-backed trace store.

    CREATE TABLE sarc_traces (
        id            BIGSERIAL PRIMARY KEY,
        session_id    TEXT,
        action_id     TEXT,
        constraint_id TEXT,
        point         TEXT,
        inserted_at   TIMESTAMPTZ DEFAULT now(),
        record        JSONB NOT NULL
    );
    CREATE INDEX ON sarc_traces (session_id);
    CREATE INDEX ON sarc_traces (action_id);
    """

    def __init__(self, dsn: str) -> None:
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = True

    def append(self, record: Any, *, session_id: Optional[str] = None) -> None:
        d = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        sid = session_id or d.get("session_id") or (
            (d.get("extra") or {}).get("execution_context", {}).get("session_id")
        )
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sarc_traces (session_id, action_id, constraint_id, point, record)"
                " VALUES (%s, %s, %s, %s, %s)",
                (sid, d.get("action_id"), d.get("constraint_id"),
                 d.get("point"), json.dumps(d)),
            )

    def list(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.iter_records(session_id))

    def iter_records(self, session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        with self._conn.cursor() as cur:
            if session_id:
                cur.execute(
                    "SELECT record FROM sarc_traces WHERE session_id = %s ORDER BY id",
                    (session_id,),
                )
            else:
                cur.execute("SELECT record FROM sarc_traces ORDER BY id")
            for (row,) in cur:
                yield row  # psycopg2 returns JSONB as dict already

    def export_jsonl(self, path: Any, *, session_id: Optional[str] = None) -> int:
        import pathlib, json as _json
        records = list(self.iter_records(session_id))
        pathlib.Path(path).write_text(
            "\n".join(_json.dumps(r) for r in records), encoding="utf-8"
        )
        return len(records)

    def close(self) -> None:
        self._conn.close()
```

Wire it in the same way as the bundled stores:

```python
class StoreBackedMemory:
    def __init__(self, store): self._store = store
    async def add_event(self, session_id, event_type, content, metadata=None):
        if event_type == "governance_event":
            self._store.append(content, session_id=session_id)

memory = StoreBackedMemory(PostgresTraceStore("postgresql://user:pass@db/sarc"))
governed = GovernanceToolset(wrapped=toolset, spec=spec,
                             memory_getter=lambda _: memory,
                             session_id_getter=lambda ctx: ctx.deps.session_id)
```

### Redis (redis-py / aioredis)

Redis Streams give you a durable, multi-writer, ordered log. Each governance
event is an entry on a per-session stream.

```python
import json
from typing import Any, Dict, Iterator, List, Optional
import redis

class RedisTraceStore:
    """Redis Streams-backed trace store.

    Each session gets its own stream: ``sarc:traces:{session_id}``.
    A global index stream ``sarc:traces:*`` holds all events for
    cross-session queries (fan-out on write).
    """

    def __init__(self, client: redis.Redis, ttl_seconds: int = 86400 * 30) -> None:
        self._r = client
        self._ttl = ttl_seconds

    def _stream_key(self, session_id: Optional[str]) -> str:
        return f"sarc:traces:{session_id or '_global'}"

    def append(self, record: Any, *, session_id: Optional[str] = None) -> None:
        d = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        sid = session_id or d.get("session_id") or "_global"
        key = self._stream_key(sid)
        self._r.xadd(key, {"record": json.dumps(d)})
        if self._ttl:
            self._r.expire(key, self._ttl)

    def list(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.iter_records(session_id))

    def iter_records(self, session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        key = self._stream_key(session_id)
        entries = self._r.xrange(key)          # [(id, {b"record": b"..."}), ...]
        for _, fields in entries:
            yield json.loads(fields[b"record"])

    def export_jsonl(self, path: Any, *, session_id: Optional[str] = None) -> int:
        import pathlib, json as _json
        records = list(self.iter_records(session_id))
        pathlib.Path(path).write_text(
            "\n".join(_json.dumps(r) for r in records), encoding="utf-8"
        )
        return len(records)

    def close(self) -> None:
        self._r.close()
```

Both adapters satisfy `TraceStore` structurally — no inheritance needed.
`sarc-governance trace verify-chain` works on any exported JSONL regardless
of which backend produced it.

## Deciding between JSONL and SQLite

- **JSONL** is simpler and `jq`-friendly but has no native filtering;
  reads always scan. Use for single-session logs that get rotated.
- **SQLite** is appropriate for retention windows where you want
  per-session look-ups. The store keeps a denormalised
  `session_id` / `action_id` / `constraint_id` index so queries by
  any of those are cheap.

Either way, the `export_jsonl` method gives you a stable inter-store
format for downstream tools.
