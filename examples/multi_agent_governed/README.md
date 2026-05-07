# Multi-agent governed pipeline

This example demonstrates SARC governance applied at two levels of a multi-agent
chain.  A coordinator agent and a validator agent each carry their own
independent `ConstraintSpec`, so governance fires at both levels and a block at
the inner agent propagates back through the outer one.

The domain is expense approval: a caller submits an expense, the coordinator
decides whether to route it through validation, and the validator decides whether
to approve it before the coordinator forwards it to an ERP system.

---

## Two-agent architecture

```
Caller
  |
  v
coordinator_governed  (CoordinatorSpec)
  |  PAG: block ERP submit if validator rejected
  |  PAG: block ERP submit if daily spend > $5,000
  |
  |-- small expense (<$500) --> erp.submit_expense  (direct, no validation)
  |
  +-- large expense (>=$500) --> delegate.validate_expense
                                       |
                                       v
                                validator_governed  (ValidatorSpec)
                                  |  PAG: block if vendor is blacklisted
                                  |  ESCALATION/PAG: escalate if amount > $2,000
                                  |  SOFT/PAA: flag duplicate expense
```

### Agent roles

| Agent | Class | What it governs |
|---|---|---|
| **Coordinator** (`coordinator-agent`) | `CoordinatorSpec` with `GovernanceToolset` | Controls what reaches the ERP: rejects submissions where the validator returned `approved=False`, and enforces a $5,000 daily spend cap across the session. |
| **Validator** (`validator-agent`) | `ValidatorSpec` with `GovernanceToolset` | Controls what can be validated: blocks blacklisted vendors outright, escalates large amounts for human review, and flags duplicate submissions post-action. |

Each agent is constructed independently with its own `ConstraintSpec`,
`EscalationRouter`, and session memory.  Neither agent shares state with the
other at the governance layer.

---

## Governance boundaries

### Coordinator constraints (`CoordinatorSpec`)

| Constraint ID | Class | Point | Trigger | Response |
|---|---|---|---|---|
| `block_rejected_expense` | hard | PAG | `erp.submit_expense` called when validator returned `approved=False` | Raises `ConstraintViolation` before ERP is touched |
| `block_daily_limit` | hard | PAG | `erp.submit_expense` would push daily spend above $5,000 | Raises `ConstraintViolation` before ERP is touched |

### Validator constraints (`ValidatorSpec`)

| Constraint ID | Class | Point | Trigger | Response |
|---|---|---|---|---|
| `block_blacklisted_vendor` | hard | PAG | Vendor name is in the denylist (`shadow-corp`, `off-books-llc`) | Raises `ConstraintViolation`; inner toolset never called |
| `escalate_large_expense` | escalation | PAG | Amount exceeds $2,000 | Calls escalation handler, then proceeds |
| `flag_duplicate_expense` | soft | PAA | Post-action result contains `duplicate: true` | Logs a trace record; never blocks |

The hard boundary between the two agents means that a blacklist check at the
validator cannot be bypassed by the coordinator, and a daily-spend limit at the
coordinator cannot be bypassed by the validator approving an expense.

---

## Run command

```
python examples/multi_agent_governed/run_demo.py
```

No external services are required.  Both toolsets are in-process Python objects.

---

## Expected output excerpt

```
=================================================================
Multi-agent governed pipeline — expense approval
Coordinator spec: 2 constraints | Validator spec: 3 constraints
=================================================================

  [OK]       Small expense — direct ERP submit, no validation
              vendor=office-supplies-co  amount=$150

  [OK]       Large expense — validator approves, ERP submit succeeds
              vendor=cloud-vendor  amount=$800

  [BLOCKED]  Very large expense — escalated at validator, but still within limit
              vendor=consulting-firm  amount=$2,500 +ESCALATION
              constraint=block_blacklisted_vendor at PAG

  [BLOCKED]  Blacklisted vendor — blocked at validator before any check
              vendor=shadow-corp  amount=$600
              constraint=block_blacklisted_vendor at PAG

  [BLOCKED]  Daily spend limit — blocked at coordinator after prior approvals
              vendor=office-supplies-co  amount=$4,200 +ESCALATION
              constraint=block_daily_limit at PAG
```

---

## Trace interpretation

Each agent writes `TraceRecord` objects to its own session memory as
`governance_event` entries.  Because the two agents use separate `SimpleMemory`
instances, their trace logs are independent:

- The **coordinator trace** records every PAG evaluation against
  `CoordinatorSpec` — including calls to `delegate.validate_expense` and
  `erp.submit_expense`.
- The **validator trace** records every PAG and PAA evaluation against
  `ValidatorSpec` — including the blacklist check, escalation check, and
  duplicate flag.

When the validator raises `ConstraintViolation`, the exception propagates
through `CoordinatorToolset.call_tool` to the coordinator's
`GovernanceToolset`.  The coordinator does not suppress it; it surfaces to the
caller as-is, carrying the original `constraint_id` and `point`.  Both agents
have independently recorded the event in their own traces.

To inspect all trace records after a run, call
`memory.governance_events()` on whichever memory instance you want to
examine.

---

## How to adapt

The two-agent pattern generalises to any domain where different policy concerns
belong at different levels of an agent hierarchy.  Three examples:

### Customer support agent with refund thresholds

```
coordinator_spec = ConstraintSpec(constraints=[
    # Hard: block refunds above agent authority level
    Constraint(id="block_large_refund", klass="hard", verif="PAG",
               response="block_or_escalate",
               predicate=lambda ctx: ctx["args"].get("amount", 0) > 200,
               description="Refunds above $200 require supervisor approval."),
    # Soft: accumulate daily refund total for reporting
    Constraint(id="log_daily_refund", klass="soft", verif="PAA",
               response="throttle_log",
               predicate=lambda ctx: ctx["tool"] == "crm.issue_refund",
               description="Log every refund for daily reconciliation."),
])
```

### Research agent with restricted data-source access

```
validator_spec = ConstraintSpec(constraints=[
    # Hard: block queries to sources not in the approved list
    Constraint(id="block_unapproved_source", klass="hard", verif="PAG",
               response="block_or_escalate",
               predicate=lambda ctx: ctx["args"].get("source") not in APPROVED_SOURCES,
               description="Only approved data sources may be queried."),
    # Escalation: flag queries that return PII fields
    Constraint(id="escalate_pii_result", klass="escalation", verif="PAA",
               response="escalate",
               predicate=lambda ctx: any(f in ctx.get("result", {}) for f in PII_FIELDS),
               description="Escalate results containing PII fields."),
])
```

### Procurement agent with spend limits and vendor denylist

```
coordinator_spec = ConstraintSpec(constraints=[
    Constraint(id="block_denylist_vendor", klass="hard", verif="PAG",
               response="block_or_escalate",
               predicate=lambda ctx: ctx["args"].get("vendor") in VENDOR_DENYLIST,
               description="Block purchase orders to denied vendors."),
    Constraint(id="block_over_budget", klass="hard", verif="PAG",
               response="block_or_escalate",
               predicate=lambda ctx: ctx["args"].get("amount", 0) > BUDGET_REMAINING,
               description="Block POs that would exceed remaining budget."),
])
```

Replace the predicate lambdas with named functions or registered predicate
strings for YAML-driven specs (see `docs/policy-cookbook.md`).

---

## Limitations

- **Single-process** — both agents run in the same Python process.  There is no
  real network boundary between them; `CoordinatorToolset` calls
  `validator_governed.call_tool(...)` as a direct Python method call.  In a
  real KAOS deployment each agent would run in its own pod and communicate over
  MCP/HTTP.
- **In-memory session memory** — `SimpleMemory` stores events in a plain
  Python list.  Traces are lost when the process exits.  In production, supply
  a `MemoryProtocol` implementation backed by a database or message queue.
- **No concurrent calls** — `GovernanceToolset` is single-actor per instance.
  Parallel tool calls from the same agent require per-call context isolation,
  which is out of scope for this example.
