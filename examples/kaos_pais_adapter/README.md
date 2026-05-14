# KAOS PAIS x SARC Governance adapter

This example shows two ways to integrate SARC runtime governance into a KAOS
deployment:

1. **`create_governed_agent_server` (canonical production approach)** — wraps
   the entire KAOS `AgentServer`, governing every registered toolset
   (`DelegationToolset` and `MCPServerStreamableHTTP`) automatically.
   No KAOS source modification required.

2. **`build_governed_toolset` (legacy single-toolset approach)** — wraps a
   single `DelegationToolset` explicitly.  Kept for backwards compatibility.

`run_demo.py` exercises the adapter end-to-end without requiring a running KAOS
cluster.

---

## What KAOS / PAIS is

**KAOS** (Kubernetes Agentic Orchestration System) is a Kubernetes-native
platform for deploying multi-agent systems as pods.  Agents communicate through
typed MCP calls; each agent runs inside a `pydantic-ai-server` (PAIS) process.

Key PAIS types this adapter touches:

| PAIS type | Role |
|---|---|
| `pais.tools.DelegationToolset` | Exposes registered sub-agents as `delegate_to_{name}` tools and routes MCP calls to `MCPServerStreamableHTTP` targets. |
| `pais.memory.LocalMemory` | Session-scoped event store attached to every agent via `RunContext[AgentDeps].deps.memory`. |
| `pais.serverutils.AgentDeps` | Deps object holding `memory`, `session_id`, `tenant_id`, and RBAC `roles`; available at `ctx.deps`. |
| `pydantic_ai.RunContext[AgentDeps]` | The context object passed into every tool call by pydantic-ai. |

---

## How SARC maps governance requirements into runtime checks

### Canonical: `create_governed_agent_server`

```python
from sarc_governance.adapters.pais import create_governed_agent_server
from sarc_governance import load_spec

spec   = load_spec("/config/sarc_spec.yaml")
server = create_governed_agent_server(
    spec,
    agent_name=settings.agent_name,
    tenant_id=settings.tenant_id,
)
app = server.app  # FastAPI application
```

This calls KAOS's `create_agent_server(**kwargs)` normally, then wraps every
toolset in `server._agent._toolsets` with a `SARCGovernanceToolset`.  Both
`DelegationToolset` (sub-agent delegation) and `MCPServerStreamableHTTP` (MCP
tool calls) are governed.

### Legacy: `build_governed_toolset`

```python
from sarc_governance.adapters.pais import build_governed_toolset

governed = build_governed_toolset(
    delegation_toolset=DelegationToolset(...),
    agent_name=settings.agent_name,
    spec=spec,
)
```

Wraps a single toolset.  Use `create_governed_agent_server` for new deployments.

---

Every tool call routed through the wrapper runs through three enforcement
points automatically:

- **PAG (Pre-Action Gate)** — evaluated *before* the inner toolset is called.
  Hard and escalation constraints live here.
- **ATM (Action-Time Monitor)** — evaluated *during* execution (e.g. elapsed
  time checks).
- **PAA (Post-Action Auditor)** — evaluated *after* the inner toolset returns.
  Soft and escalation constraints live here.

Every evaluation produces a `TraceRecord` written to `ctx.deps.memory` as a
`governance_event`, giving full audit coverage in PAIS session memory with no
extra wiring.

---

## Scenario overview

The demo drives six realistic scenarios through the governed toolset:

| # | Label | Tool | Expected outcome |
|---|---|---|---|
| 1 | Allowed delegation to finance_agent | `delegate_to_finance_agent` | OK — agent is in the allowed list |
| 2 | Allowed MCP tool call (low value) | `erp.create_po` | OK — amount $4,500 is below the $50,000 threshold |
| 3 | BLOCKED — delegation to unknown agent | `delegate_to_shadow_agent` | BLOCKED — agent not in allowed list (`block_unknown_agent`) |
| 4 | BLOCKED — high-value purchase order | `erp.create_po` | BLOCKED — amount $75,000 exceeds $50,000 limit (`block_high_value_action`) |
| 5 | ESCALATED — cross-tenant data query | `db.query` | OK+ESC — caller tenant ≠ target tenant; escalation handler called (`escalate_cross_tenant`) |
| 6 | Allowed delegation to data_agent | `delegate_to_data_agent` | OK — agent is in the allowed list |

---

## Run command

```
python examples/kaos_pais_adapter/run_demo.py
```

No additional dependencies beyond `sarc-governance` itself are required; the
demo uses stand-in classes that mirror the real PAIS signatures.

---

## Expected output excerpt

```
=================================================================
KAOS PAIS × SARC Governance — integration example
=================================================================

  [OK]      Allowed delegation to finance_agent
             tool=delegate_to_finance_agent
             finance_agent completed: generate Q1 report

  [OK]      Allowed MCP tool call (low value)
             tool=erp.create_po
             {'tool': 'erp.create_po', 'args': {'vendor': 'acme-supplies', ...

  [BLOCKED] BLOCKED — delegation to unknown agent
             tool=delegate_to_shadow_agent
             constraint=block_unknown_agent at PAG

  [BLOCKED] BLOCKED — high-value purchase order
             tool=erp.create_po
             constraint=block_high_value_action at PAG

  [ESCALATION] constraint=escalate_cross_tenant tool=db.query agent=coordinator-agent
  [OK+ESC]  ESCALATED — cross-tenant data query
             tool=db.query
             {'tool': 'db.query', 'args': {'table': 'customers', ...

  [OK]      Allowed delegation to data_agent
             tool=delegate_to_data_agent
             data_agent completed: summarise sales data
```

---

## SARC's three runtime outcomes

**Allowed [OK]**
The tool call satisfies all active constraints (no predicate fires at PAG/ATM,
or the PAA soft constraint fires but does not block).  The inner toolset's
result is returned to the caller unchanged.

**Blocked [BLOCKED]**
A hard constraint's predicate fires at PAG or ATM.  `GovernanceToolset` raises
`ConstraintViolation` immediately; the inner toolset is never called (for PAG)
or is interrupted (for ATM).  The exception carries `constraint_id` and `point`
for structured error handling.

**Escalated-but-allowed [OK+ESC]**
An escalation constraint's predicate fires.  The action is *not* blocked — the
inner toolset call proceeds and its result is returned normally.  In parallel,
the `EscalationRouter` invokes the registered `escalation_handler` async
callable with the `TraceRecord` and call context.  Use this to trigger human
review, write to a ticketing system, or page on-call staff, without interrupting
the agent's flow.

---

## Files in this directory

| File | Purpose |
|---|---|
| `adapter.py` | Re-exports `build_governed_toolset` from the library for backwards compatibility. New deployments should import from `sarc_governance.adapters.pais` directly. |
| `run_demo.py` | Runnable demo with stand-in PAIS types.  Exercises all six scenarios. No real KAOS cluster required. |

---

## Limitations

- **Stand-in types** — `run_demo.py` uses `PAISMemory`, `KAOSDelegationToolset`,
  `AgentDeps`, and `PAISContext` as stand-ins.  They mirror the public
  signatures of their real PAIS counterparts but do not import from PAIS.
  Swapping in the real classes requires no changes to `adapter.py`.
- **Escalation handler is in-memory** — the demo's `_escalation_handler`
  appends to a plain Python list and prints to stdout.  In production, replace
  it with a queue, ticketing system, or paging integration.
- **No real KAOS cluster** — sub-agent delegation is simulated by
  `MockSubAgent.process_message`.  Real MCP routing via
  `MCPServerStreamableHTTP` is not exercised.

---

## Further reading

- [docs/integrations.md](../../docs/integrations.md) — adapter patterns for
  LangGraph, OpenAI tool calling, AWS Bedrock, and custom toolsets.
- [docs/mental-model.md](../../docs/mental-model.md) — a plain-language
  explanation of PAG/ATM/PAA, constraint classes, and how the enforcement loop
  works.
