"""Pre-production trace store demo.

End-to-end illustration of the foundations added for pre-production use:

1. Load a YAML spec, attach :class:`PolicyMetadata`, compute a checksum.
2. Wire a :class:`SQLiteTraceStore` (with hash chaining enabled) into a
   ``GovernanceToolset`` via a small ``MemoryProtocol`` adapter.
3. Run a few governed tool calls, populating the trace store.
4. Verify the resulting hash chain.
5. Exercise ``inspect_policy`` and ``diff_policies`` against a perturbed
   spec.

Run::

    python examples/preproduction_trace_store/run_demo.py

It writes ``trace.sqlite`` and ``trace.jsonl`` to the example directory
and prints a transcript suitable for CI logs. Re-runs are idempotent —
the SQLite store is removed at the start of each run for cleanliness.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any, Dict

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ExecutionContext,
    GovernanceToolset,
    PolicyMetadata,
    SQLiteTraceStore,
    diff_policies,
    inspect_policy,
    load_spec,
    policy_checksum,
    verify_chain,
)


HERE = pathlib.Path(__file__).resolve().parent
SPEC_PATH = HERE.parent / "procurement_agent" / "sarc_spec.yaml"
SQLITE_PATH = HERE / "trace.sqlite"
JSONL_EXPORT_PATH = HERE / "trace.jsonl"


# ---------------------------------------------------------------------------
# Adapter: TraceStore -> MemoryProtocol
# ---------------------------------------------------------------------------


class StoreBackedMemory:
    """Tiny ``MemoryProtocol`` shim that fans events into a TraceStore."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        if event_type == "governance_event":
            self._store.append(content, session_id=session_id)


# ---------------------------------------------------------------------------
# Mock toolset
# ---------------------------------------------------------------------------


class FakeERPToolset:
    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Dict[str, Any]:
        # Trivial stub: return a deterministic fake response.
        return {
            "status": "ok",
            "tool": name,
            "amount": tool_args.get("amount"),
            "po_id": "PO-1234",
        }


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("SARC Governance — pre-production trace store demo")
    print("=" * 60)

    # Clean slate.
    if SQLITE_PATH.exists():
        SQLITE_PATH.unlink()
    if JSONL_EXPORT_PATH.exists():
        JSONL_EXPORT_PATH.unlink()

    # 1. Load the spec, attach metadata, print checksum.
    spec = load_spec(SPEC_PATH)
    meta = PolicyMetadata(
        policy_id="procurement",
        version="1.0.0",
        owner="security@example.com",
        description="Procurement constraints, demo bundle.",
        approval_status="approved",
        approved_by="security@example.com",
        checksum=policy_checksum(spec),
    )
    print()
    print(f"spec:        {SPEC_PATH}")
    print(f"checksum:    {meta.checksum}")
    print(f"version:     {meta.version}")
    print(f"approved by: {meta.approved_by} ({meta.approval_status})")

    # 2. Build a store-backed memory and a governed toolset.
    store = SQLiteTraceStore(SQLITE_PATH, hash_chain=True)
    memory = StoreBackedMemory(store)
    governed = GovernanceToolset(
        wrapped=FakeERPToolset(),
        spec=spec,
        memory_getter=lambda ctx: memory,
        session_id_getter=lambda ctx: "sess-2026-05-06",
        context_getter=lambda ctx: ExecutionContext(
            principal_id="alice@example.com",
            agent_id="procurement-agent-v3",
            tenant_id="acme",
            session_id="sess-2026-05-06",
            roles=("procurement", "approver"),
            environment="staging",
            request_id="req-4f8c2d",
        ),
    )

    # 3. Run a couple of governed calls.
    print()
    print("running 3 governed tool calls...")
    try:
        await governed.call_tool("erp.create_po", {"amount": 1_000})  # passes
        await governed.call_tool("erp.create_po", {"amount": 1_500, "first_time_supplier": False})
        # This one trips the hard PAG block.
        await governed.call_tool("erp.create_po", {"amount": 75_000})
    except Exception as exc:  # ConstraintViolation
        print(f"  blocked: {type(exc).__name__}: {exc}")

    # 4. Inspect store and verify chain.
    records = store.list()
    store.close()
    print()
    print(f"trace store has {len(records)} record(s)")
    breaks = verify_chain(records)
    if not breaks:
        print("hash chain: OK")
    else:
        print(f"hash chain: BROKEN ({len(breaks)} issue(s))")
        for b in breaks:
            print(f"  - index={b.index} reason={b.reason}")
        raise SystemExit(1)

    # 5. Export to JSONL and verify the export too.
    store2 = SQLiteTraceStore(SQLITE_PATH)
    try:
        n = store2.export_jsonl(JSONL_EXPORT_PATH)
    finally:
        store2.close()
    print(f"exported {n} record(s) to {JSONL_EXPORT_PATH}")

    exported = []
    for line in JSONL_EXPORT_PATH.read_text().splitlines():
        if line.strip():
            exported.append(json.loads(line))
    breaks = verify_chain(exported)
    print("exported hash chain: " + ("OK" if not breaks else f"BROKEN ({len(breaks)})"))

    # 6. Show a synthetic policy diff.
    print()
    print("simulating a policy edit and diffing...")
    edited = ConstraintSpec(
        constraints=[
            *spec.constraints[:1],  # keep ch_high_value_po unchanged
            # Replace ce_first_time_supplier with a softer response
            Constraint(
                id="ce_first_time_supplier",
                klass="escalation",
                verif="PAG",
                response="escalate",  # was: suspend_route_default_deny
                predicate=spec.constraints[1].predicate,
                description="downgraded to plain escalate",
            ),
            spec.constraints[2],
        ]
    )
    diff = diff_policies(spec, edited)
    summary = inspect_policy(edited)
    print(f"new checksum: {summary['checksum']}")
    print(
        f"diff: +{len(diff['added'])}  -{len(diff['removed'])}  "
        f"~{len(diff['changed'])}  ={len(diff['unchanged'])}"
    )
    for ch in diff["changed"]:
        print(f"  ~ {ch['id']}: {', '.join(ch['fields'])}")

    print()
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
