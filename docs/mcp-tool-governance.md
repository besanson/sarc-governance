# MCP Tool Governance

This page explains how to govern MCP (Model Context Protocol) tools using SARC's adapter pattern.

## Scope

**SARC governs only tool boundaries that are explicitly wrapped by a `GovernanceToolset`.**

An MCP server exposes a set of tools. If you wrap the MCP client's dispatch method with a `GovernanceToolset`, every call routed through that wrapper is governed. Tools called directly on the MCP client — or through any other code path — are not governed, even if they are registered in the same MCP server.

The adapter pattern makes the governed boundary explicit:

```
Agent
  └─ GovernanceToolset          ← SARC enforces here
       └─ MCPToolset (adapter)
            └─ MCP client
                 └─ MCP server (tool implementations)
```

Tools dispatched through any other path bypass the governance surface entirely.

## Adapter pattern

Implement `ToolsetProtocol` as a thin wrapper around your MCP client:

```python
from typing import Any, Dict
from sarc_governance import GovernanceToolset, ConstraintSpec

class MCPToolset:
    """Wraps an MCP client to satisfy ToolsetProtocol."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        return await self._client.call_tool(name, tool_args)

governed = GovernanceToolset(wrapped=MCPToolset(mcp_client), spec=spec)
```

No subclassing, no framework-specific imports in sarc-governance itself.

## Constraint spec for MCP tools

### Block a specific tool entirely

```python
Constraint(
    id="block_execute_shell",
    klass="hard",
    verif="PAG",
    response="block_or_escalate",
    predicate=lambda ctx: ctx["tool"] == "execute_shell",
    description="Prevent shell execution via MCP.",
)
```

### Allow only an explicit list of tools

```python
ALLOWED = {"read_file", "list_directory", "search"}

Constraint(
    id="allowlist",
    klass="hard",
    verif="PAG",
    response="block_or_escalate",
    predicate=lambda ctx: ctx["tool"] not in ALLOWED,
    description="Block any tool not in the explicit allowlist.",
)
```

### Escalate writes to sensitive paths

```python
SENSITIVE = {"/etc/", "/root/", "/sys/"}

Constraint(
    id="escalate_sensitive_write",
    klass="escalation",
    verif="PAG",
    response="escalate",
    predicate=lambda ctx: (
        ctx["tool"] == "write_file"
        and any(ctx["args"].get("path", "").startswith(p) for p in SENSITIVE)
    ),
)
```

### Soft-log all file writes for audit

```python
Constraint(
    id="log_file_writes",
    klass="soft",
    verif="PAA",
    response="throttle_log",
    predicate=lambda ctx: ctx["tool"] == "write_file",
    description="Emit a soft audit record for every file write.",
)
```

## Predicate context shape

| Enforcement point | Keys available |
|---|---|
| PAG | `tool`, `args`, `execution_context` (if wired) |
| ATM | `tool`, `args`, `result`, `elapsed`, `execution_context` |
| PAA | `tool`, `args`, `result`, `execution_context` |

`elapsed` is wall-clock seconds from dispatch to return.

## Identity stamping

Wire `ExecutionContext` to stamp user, session, or tenant onto every trace record:

```python
from sarc_governance.context import ExecutionContext

def context_getter(ctx: Any) -> ExecutionContext:
    return ExecutionContext(
        principal_id=ctx.user_id,
        session_id=ctx.session_id,
        environment="production",
    )

governed = GovernanceToolset(
    wrapped=MCPToolset(client),
    spec=spec,
    context_getter=context_getter,
)
```

Predicates then access `ctx["execution_context"]["principal_id"]` etc.

## Trace persistence

To persist trace records to a durable store, pass a `memory_getter`:

```python
from sarc_governance.stores import JSONLTraceStore

store = JSONLTraceStore("mcp_governance.jsonl", hash_chain=True)

class _StoreMemory:
    async def add_event(self, session_id, event_type, content, metadata=None):
        if event_type == "governance_event":
            store.append(content, session_id=session_id)

governed = GovernanceToolset(
    wrapped=MCPToolset(client),
    spec=spec,
    memory_getter=lambda ctx: _StoreMemory(),
    session_id_getter=lambda ctx: ctx.session_id,
)
```

Verify chain integrity after a session:

```bash
sarc-governance trace verify-chain mcp_governance.jsonl
```

## Running the demo

The demo runs with no external dependencies:

```bash
python examples/mcp_tool_governance/run_demo.py
```

It exercises all three constraint classes (hard block, escalation, soft log) against an in-process stub MCPToolset. Scenario 6 demonstrates an ungoverned direct call to illustrate the scope boundary.

## What is not governed

- MCP tool **implementations** on the server side. SARC enforces at the client dispatch boundary; server-side execution is outside SARC's scope.
- MCP server **authentication** or **capability negotiation**. SARC does not inspect the MCP protocol; it intercepts the tool dispatch call in your application code.
- Tools dispatched through any code path that bypasses the `GovernanceToolset`.
- Agent planning, prompt construction, or model outputs upstream of tool dispatch.

These are governed by other layers (network policies, IAM, server-side access control). SARC adds the runtime enforcement loop and the typed audit trail at the dispatch boundary.

## Checklist

Before shipping a governed MCP integration:

- [ ] All tool dispatch routes through `GovernanceToolset` — no direct MCP client calls in production code paths.
- [ ] Constraint spec is validated: `sarc-governance validate config/spec.yaml`
- [ ] `ExecutionContext` is wired (`context_getter`) to stamp identity on trace records.
- [ ] Trace store is durable (not `MemoryTraceStore`) for production sessions.
- [ ] Escalation handler notifies a real operator channel, not just logs.
- [ ] `audit_trace` is exercised in CI against a sample trace.
