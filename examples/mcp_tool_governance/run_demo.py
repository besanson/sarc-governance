"""MCP Tool Governance Example — allow / block / escalate.

Demonstrates how to govern MCP-style tools using SARC's adapter pattern.

No external API keys, MCP server, or Claude client required.  The tool
registry is an in-process stub.

Key point
---------
SARC governs **only tool boundaries that are explicitly wrapped**.  MCP tools
called outside the GovernanceToolset are not governed by SARC, even if they
run in the same process or are registered in the same MCP server.  The
adapter pattern makes the governed boundary explicit and inspectable.

Scenarios
---------
1. read_file /data/report.csv      → ALLOW
2. execute_shell 'ls -la'          → BLOCK  (hard constraint at PAG)
3. write_file /etc/hosts           → ESCALATE (escalation constraint at PAG,
                                               execution continues)
4. send_email team@example.com     → ALLOW + soft-log at PAA
5. write_file /tmp/output.txt      → ALLOW
6. Ungoverned direct call          → bypasses SARC entirely (illustrates scope)

Trace verification
------------------
All governed calls emit trace records to a JSONL file with a tamper-evident
SHA-256 hash chain.  The demo verifies the chain at the end using the
``sarc-governance trace verify-chain`` CLI command.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    ConstraintViolation,
    GovernanceToolset,
)
from sarc_governance.escalation import EscalationRouter
from sarc_governance.stores import JSONLTraceStore
from sarc_governance.trace import TraceRecord

# ---------------------------------------------------------------------------
# Stub MCP tool registry (replaces an actual MCP client/server connection)
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: Dict[str, Any] = {
    "read_file": lambda args: {"content": f"<contents of {args['path']}>"},
    "write_file": lambda args: {"written": args["path"]},
    "execute_shell": lambda args: {"stdout": f"ran: {args['command']}"},
    "send_email": lambda args: {"sent_to": args["to"]},
}


class MCPToolset:
    """Minimal MCP-style toolset: dispatches calls to locally registered handlers.

    In production this would be a real MCP client wrapping an MCP server.
    The SARC adapter pattern is identical either way.
    """

    async def call_tool(self, name: str, tool_args: Dict[str, Any], ctx: Any, tool: Any) -> Any:
        handler = _TOOL_REGISTRY.get(name)
        if handler is None:
            raise ValueError(f"Unknown MCP tool: {name!r}")
        return handler(tool_args)


# ---------------------------------------------------------------------------
# Trace persistence via JSONLTraceStore
# ---------------------------------------------------------------------------


class _StoreBackedMemory:
    """Bridges GovernanceToolset's MemoryProtocol to a JSONLTraceStore."""

    def __init__(self, store: JSONLTraceStore) -> None:
        self._store = store

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if event_type == "governance_event":
            self._store.append(content, session_id=session_id)


# ---------------------------------------------------------------------------
# Governance constraints
# ---------------------------------------------------------------------------

_BLOCKED_TOOLS = {"execute_shell"}
_SENSITIVE_WRITE_PREFIXES = {"/etc/", "/root/", "/sys/", "/boot/"}


def _is_blocked_tool(ctx: Dict[str, Any]) -> bool:
    return ctx["tool"] in _BLOCKED_TOOLS


def _is_sensitive_write(ctx: Dict[str, Any]) -> bool:
    if ctx["tool"] != "write_file":
        return False
    path: str = ctx["args"].get("path", "")
    return any(path.startswith(p) for p in _SENSITIVE_WRITE_PREFIXES)


def _is_email_send(ctx: Dict[str, Any]) -> bool:
    return ctx["tool"] == "send_email"


spec = ConstraintSpec(
    constraints=[
        Constraint(
            id="block_shell_execution",
            klass="hard",
            verif="PAG",
            response="block_or_escalate",
            predicate=_is_blocked_tool,
            description="Prevent direct shell execution via MCP tools.",
        ),
        Constraint(
            id="escalate_sensitive_filesystem_write",
            klass="escalation",
            verif="PAG",
            response="escalate",
            predicate=_is_sensitive_write,
            description="Route writes to sensitive filesystem paths through the Escalation Router.",
        ),
        Constraint(
            id="log_email_sends",
            klass="soft",
            verif="PAA",
            response="throttle_log",
            predicate=_is_email_send,
            description="Emit a soft audit record for every outbound email send.",
        ),
    ]
)

# ---------------------------------------------------------------------------
# Escalation handler
# ---------------------------------------------------------------------------

escalation_log: List[TraceRecord] = []


async def _escalation_handler(record: TraceRecord, ctx: Dict[str, Any]) -> None:
    escalation_log.append(record)
    print(
        f"  [ER] constraint={record.constraint_id!r}"
        f"  tool={record.tool!r}"
        f"  point={record.point.value}"
    )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("MCP Tool Governance Demo")
    print("=" * 60)
    print()
    print(
        "SARC governs only tools routed through the GovernanceToolset.\n"
        "Direct calls to MCPToolset bypass enforcement entirely.\n"
    )

    _inner = MCPToolset()
    session_id = "mcp-demo-session"

    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = Path(tmpdir) / "mcp_governance.jsonl"
        store = JSONLTraceStore(trace_path, hash_chain=True)
        memory = _StoreBackedMemory(store)

        governed = GovernanceToolset(
            wrapped=_inner,
            spec=spec,
            router=EscalationRouter(handler=_escalation_handler),
            memory_getter=lambda ctx: memory,
            session_id_getter=lambda ctx: session_id,
        )

        # 1. Allow: read file
        print("1. read_file /data/report.csv → ALLOW")
        result = await governed.call_tool("read_file", {"path": "/data/report.csv"})
        print(f"   {result}\n")

        # 2. Block: shell execution (hard constraint at PAG)
        print("2. execute_shell 'ls -la' → BLOCK (hard constraint, PAG)")
        try:
            await governed.call_tool("execute_shell", {"command": "ls -la"})
            print("   ERROR: should have been blocked\n")
        except ConstraintViolation as exc:
            print(f"   blocked — constraint={exc.constraint_id!r}  point={exc.point.value}\n")

        # 3. Escalate: sensitive write (escalation at PAG, execution continues)
        print("3. write_file /etc/hosts → ESCALATE (escalation constraint, PAG)")
        result = await governed.call_tool(
            "write_file", {"path": "/etc/hosts", "content": "127.0.0.1 localhost"}
        )
        print(f"   escalated to ER; execution continued → {result}\n")

        # 4. Allow + soft-log: email send (soft constraint fires at PAA after success)
        print("4. send_email team@example.com → ALLOW + soft audit log (PAA)")
        result = await governed.call_tool(
            "send_email", {"to": "team@example.com", "body": "Deployment complete."}
        )
        print(f"   {result}\n")

        # 5. Allow: safe write
        print("5. write_file /tmp/output.txt → ALLOW")
        result = await governed.call_tool(
            "write_file", {"path": "/tmp/output.txt", "content": "ok"}
        )
        print(f"   {result}\n")

        # 6. Ungoverned direct call — illustrates scope boundary
        print("6. Direct call to MCPToolset (ungoverned, bypasses SARC) → execute_shell")
        raw = await _inner.call_tool("execute_shell", {"command": "echo hi"}, None, None)
        print(f"   result: {raw}")
        print("   ^ This call was NOT governed. No trace record was emitted.\n")

        store.close()

        print(f"Escalations routed to ER: {len(escalation_log)}")
        for r in escalation_log:
            print(f"  - {r.constraint_id}  tool={r.tool}  fired={r.fired}")

        trace_records = store.list()
        print(f"\nTrace records written to JSONL: {len(trace_records)}")

        # Verify the hash chain end-to-end
        print()
        print("─" * 60)
        print("Verifying trace hash chain …")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "sarc_governance.cli",
                "trace",
                "verify-chain",
                str(trace_path),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            print("  chain OK — governed MCP call → JSONL trace → verify-chain passed.")
        else:
            print("  Hash chain verification FAILED.")
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr)
            sys.exit(1)
        print("─" * 60)

    print()
    print("=" * 60)
    print("Done")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
