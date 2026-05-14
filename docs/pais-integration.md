# PAIS Integration Guide

This page covers integrating SARC runtime governance into a [KAOS](https://github.com/axsaucedo/kaos) PAIS deployment. PAIS uses pydantic-ai toolsets (`DelegationToolset`, `MCPServerStreamableHTTP`) to route tool calls; SARC wraps that boundary to enforce constraints before, during, and after every call.

## Canonical production integration

**Use `create_governed_agent_server` as a drop-in replacement for KAOS's `create_agent_server`.**

```python
from sarc_governance.adapters.pais import create_governed_agent_server
from sarc_governance import load_spec

spec   = load_spec("/config/sarc_spec.yaml")
server = create_governed_agent_server(
    spec,
    agent_name=settings.agent_name,
    tenant_id=settings.tenant_id,
)
app = server.app  # FastAPI application — deploy as-is
```

`create_governed_agent_server` forwards all keyword arguments verbatim to KAOS's `create_agent_server`, then replaces every toolset in `server._agent._toolsets` with a `SARCGovernanceToolset` wrapper.  **No KAOS source modification is required.**  The returned `AgentServer` is identical to the one KAOS normally produces, except that every tool call — sub-agent delegation (`DelegationToolset`) and MCP tool calls (`MCPServerStreamableHTTP`) — passes through SARC's PAG/ATM/PAA enforcement loop.

### Why this approach

The KAOS `create_agent_server` function builds a pydantic-ai `Agent` and appends all registered toolsets to `agent._toolsets` internally.  SARC intercepts *after* construction by replacing each toolset with a `SARCGovernanceToolset` wrapper before the FastAPI app handles any requests.  This ensures:

- **All toolsets are governed** — both `DelegationToolset` (sub-agent routing) and `MCPServerStreamableHTTP` (direct MCP calls).  The legacy `build_governed_toolset` pattern only covered explicitly-wrapped toolsets.
- **No KAOS internals modified** — `create_agent_server` runs unchanged; SARC patches the result, not the source.
- **Drop-in compatible** — the same `AgentServer` type is returned, so deployment scripts, health probes, and A2A discovery routes work identically.

### Installation

`sarc-governance` has no dependency on `pais` or `kaos`. Install them separately:

```bash
pip install sarc-governance
pip install -e path/to/kaos/pydantic-ai-server   # from source or your internal registry
```

## SARCGovernanceToolset

`create_governed_agent_server` wraps each toolset with a `SARCGovernanceToolset` instance.  It implements the pydantic-ai `AbstractToolset` duck-typed interface:

| Method | Behaviour |
|---|---|
| `id` | Returns the wrapped toolset's `id`. |
| `get_tools(ctx)` | Delegated to the wrapped toolset — pydantic-ai uses this to build the LLM tool schema. |
| `call_tool(name, tool_args, ctx, tool)` | Enforces PAG/ATM/PAA, then delegates to the wrapped toolset. |

The pydantic-ai agent runtime calls these methods identically to any other toolset — SARC enforcement is transparent.

## Governance context mapping

PAIS `AgentDeps` exposes `session_id` and `memory` but does not provide `tenant_id`, `roles`, `principal_id`, or `environment` by default. SARC's `PAISContextMapper` bridges this gap.

```python
from sarc_governance.adapters.pais import PAISContextMapper, GovernanceToolset

mapper = PAISContextMapper(
    agent_name="procurement-approver",
    tenant_id="acme-corp",          # override: always use this value
    roles=("procurement-manager",), # override: stamp on every trace
    environment="production",
    principal_id="",                # falls back to ctx.deps.principal_id if empty
)

governed = GovernanceToolset(
    wrapped=delegation_toolset,
    spec=spec,
    context_getter=mapper,
)
```

`create_governed_agent_server` configures `PAISContextMapper` automatically using its `agent_name`, `tenant_id`, `roles`, `environment`, and `principal_id` parameters.

### Fallback behaviour

| Field | Supplied at construction | Not supplied |
|---|---|---|
| `agent_id` | Always uses `agent_name` | — |
| `tenant_id` | Uses constructor value | Falls back to `ctx.deps.tenant_id` |
| `roles` | Uses constructor value | Falls back to `ctx.deps.roles` |
| `principal_id` | Uses constructor value | Falls back to `ctx.deps.principal_id` |
| `session_id` | — | Always read from `ctx.deps.session_id` |

Predicates and trace records receive the resolved `ExecutionContext` via `ctx["execution_context"]`.

## Preventing silent trace drops

PAIS memory silently drops `add_event` calls for sessions that have not been
explicitly created.  Without a guard, governance trace records are lost without
any error or warning.

`PAISMemoryGuard` fixes this by calling `create()` once per session before the
first `add_event`, whenever the wrapped memory object exposes that method.
`create_governed_agent_server` enables this guard by default (`guard_memory=True`).

```python
from sarc_governance.adapters.pais import PAISMemoryGuard

guard = PAISMemoryGuard(ctx.deps.memory)
# Use guard as the memory argument wherever you wire GovernanceToolset.
```

Set `guard_memory=False` only if your PAIS memory implementation creates sessions
automatically, or if you pre-create the session manually before the first governed call.

> **Real upstream PAIS note:** The upstream `LocalMemory` uses an async
> `create_session(app_name, user_id, session_id)` method rather than a synchronous
> `create(session_id)`.  The guard does not call `create_session()`.  Pre-create
> the session yourself before the first governed call when using the real PAIS package:
> ```python
> await memory.create_session("my-app", "user", session_id)
> server = create_governed_agent_server(spec, guard_memory=False, ...)
> ```

## Scope of governance

**SARC governs only tool boundaries that are explicitly wrapped by a `SARCGovernanceToolset`.**

`create_governed_agent_server` wraps every toolset that `create_agent_server` registers.  Sub-agents, MCP tools, or PAIS tools that are invoked outside that wrapper (for example, toolsets added directly by a `custom_agent` after server construction) are not governed.

## Predicate context shape

Predicates receive a dict at each enforcement point:

**PAG (Pre-Action Gate):**
```python
{
    "tool": "delegate_to_finance_agent",
    "args": {"task": "...", ...},
    "execution_context": {          # present when context_getter is wired
        "agent_id": "my-agent",
        "tenant_id": "acme-corp",
        "session_id": "sess-abc",
        "roles": ["procurement-manager"],
        "environment": "production",
    }
}
```

**ATM (Action-Time Monitor):** adds `"result"` and `"elapsed"` (seconds).

**PAA (Post-Action Auditor):** adds `"result"`.

## Constraint placement for PAIS patterns

| Governance need | Constraint class | Point | Example predicate |
|---|---|---|---|
| Block unknown sub-agent | `hard` | PAG | `ctx["tool"] not in ALLOWED_AGENTS` |
| Block high-value purchase order | `hard` | PAG | `ctx["args"].get("amount", 0) >= 50_000` |
| Escalate cross-tenant delegation | `escalation` | PAG | `ctx["execution_context"]["tenant_id"] != ctx["args"].get("target_tenant")` |
| Audit all finance tool calls | `soft` | PAA | `ctx["tool"].startswith("finance.")` |
| Flag slow sub-agent calls | `soft` | ATM | `ctx.get("elapsed", 0) > 5.0` |

## Tracing and audit

Governance events are emitted to PAIS session memory as `event_type="governance_event"`. Retrieve and inspect them:

```python
events = [
    e for e in memory.list_events(session_id)
    if e["event_type"] == "governance_event"
]
```

Each event content is a `TraceRecord.to_dict()` payload:

```json
{
  "action_id": "act-1",
  "tool": "delegate_to_finance_agent",
  "point": "PAG",
  "constraint_id": "block_high_value",
  "klass": "hard",
  "fired": true,
  "response": "block_or_escalate",
  "timestamp": 1748000000.0,
  "extra": {
    "execution_context": {
      "agent_id": "procurement-approver",
      "tenant_id": "acme-corp",
      "session_id": "sess-abc"
    }
  }
}
```

For file-backed or tamper-evident audit trails, use `JSONLTraceStore` or `SQLiteTraceStore` in a `StoreBackedMemory` wrapper (see [`docs/trace-stores.md`](trace-stores.md)).

## Testing the PAIS adapter

SARC tests the adapter in two distinct ways, each with different scope:

### 1. PAIS-compatible contract test (stub)

A fast, deterministic test that runs in normal CI without any external network
access.  It installs a minimal PAIS-compatible stub from `stubs/pais_stub/` that
mirrors the SARC adapter contract.  This verifies the adapter logic but does
**not** prove compatibility with the real upstream KAOS package.

```bash
pip install -e stubs/pais_stub/
pytest tests/test_pais_integration.py -v
```

CI job: **pais-stub-integration** (Python 3.11 and 3.12).

### 2. Upstream KAOS/PAIS integration test

A separate CI job clones [axsaucedo/kaos](https://github.com/axsaucedo/kaos) and
installs the real `pydantic-ai-server` (the `pais` package) from source.  The
tests then run with `SARC_REQUIRE_REAL_PAIS=1`, which **fails** (not skips) if
the real upstream package is missing or if its API is incompatible.

```bash
git clone --depth 1 https://github.com/axsaucedo/kaos /tmp/kaos
pip install -e /tmp/kaos/pydantic-ai-server   # requires Python >= 3.12
SARC_REQUIRE_REAL_PAIS=1 pytest tests/test_pais_integration.py -q
```

CI job: **pais-upstream-integration** (Python 3.12).

The upstream test asserts that `pais.__file__` does not point to the local stub,
so it cannot accidentally pass against the contract stub even if both are installed.

### Unit tests (no pais package required)

```bash
python examples/kaos_pais_adapter/run_demo.py   # stand-in PAIS types, no pais package
python -m pytest tests/test_pais_adapter.py -v  # unit tests, no pais package
```

## Legacy: `build_governed_toolset`

The earlier `build_governed_toolset` function wraps a single toolset directly:

```python
from sarc_governance.adapters.pais import build_governed_toolset

governed = build_governed_toolset(
    delegation_toolset=DelegationToolset(sub_agents, memory, session_id),
    agent_name=settings.agent_name,
    tenant_id=settings.tenant_id,
    spec=spec,
)
```

This is still supported for backwards compatibility, but it only governs the single explicitly-wrapped toolset.  For new deployments, use `create_governed_agent_server` to govern all toolsets automatically.

## Migrating from the example adapter

If you used `examples/kaos_pais_adapter/adapter.py` in a previous deployment, the function signature is unchanged for `build_governed_toolset`:

```python
# Before (still works)
from examples.kaos_pais_adapter.adapter import build_governed_toolset

# After (preferred — canonical production approach)
from sarc_governance.adapters.pais import create_governed_agent_server
```

## What SARC does not govern

- Sub-agent internals: what the sub-agent does after receiving a delegated task.
- Tools called directly by sub-agents without routing through `SARCGovernanceToolset`.
- PAIS-level authentication, authorization, or IAM policies.
- Model outputs or prompts upstream of tool dispatch.

SARC governs the dispatch boundary; existing security controls at other layers remain in force.
