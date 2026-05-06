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

## Deciding between JSONL and SQLite

- **JSONL** is simpler and `jq`-friendly but has no native filtering;
  reads always scan. Use for single-session logs that get rotated.
- **SQLite** is appropriate for retention windows where you want
  per-session look-ups. The store keeps a denormalised
  `session_id` / `action_id` / `constraint_id` index so queries by
  any of those are cheap.

Either way, the `export_jsonl` method gives you a stable inter-store
format for downstream tools.
