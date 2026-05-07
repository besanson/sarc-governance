# Policy cookbook

This cookbook provides eight ready-to-use constraint recipes covering common
governance scenarios.  For each recipe: copy the YAML spec, register any custom
predicate in `sarc_governance/predicates.py` (or pass it as a Python callable
directly), then wrap your toolset:

```python
from sarc_governance import GovernanceToolset
from sarc_governance.specs import load_spec

spec    = load_spec("path/to/your_spec.yaml")
toolset = GovernanceToolset(wrapped=your_toolset, spec=spec)
```

Named predicates referenced in the YAML (e.g. `cross_tenant_access`) must be
registered before `load_spec` is called.  Callable predicates used directly in
Python specs need no registration.  See `docs/integrations.md` for the
predicate registration API.

---

## Recipe 1: Cross-tenant data access

**Use case:** A multi-tenant SaaS platform where agents run on behalf of a
specific tenant.  An agent must never read or write data belonging to a
different tenant.

**Policy intent:** Block any tool call where the calling actor's tenant
identifier differs from the tenant identifier of the target resource.

```yaml
constraints:
  - id: block_cross_tenant_access
    class: hard
    verif: PAG
    response: block_or_escalate
    predicate: cross_tenant_access      # fires when actor.tenant_id != resource.tenant_id
    description: >
      Block tool calls where the execution context tenant_id does not match
      the tenant_id of the target resource passed in tool args.
```

**Expected behavior:**
- A query from `tenant-acme` targeting `tenant_id: tenant-acme` passes through.
- A query from `tenant-acme` carrying `tenant_id: tenant-rival` raises
  `ConstraintViolation(constraint_id="block_cross_tenant_access", point="PAG")`.
- The inner toolset is never invoked for cross-tenant calls.

**Trace expectation:** One `TraceRecord` with `fired=True`, `point="PAG"`,
`response="block_or_escalate"` per blocked call.  Allowed calls produce
`fired=False` records for full coverage.

---

## Recipe 2: PII field access

**Use case:** A data-platform agent that executes SQL queries.  Certain columns
(e.g. `email`, `ssn`, `dob`, `credit_card`) are flagged as PII and must never
be selected except by roles explicitly permitted to handle PII.

**Policy intent:** Block any query that selects one or more PII-flagged columns
unless the caller's role set includes `pii_authorized`.

```yaml
constraints:
  - id: block_pii_field_access
    class: hard
    verif: PAG
    response: block_or_escalate
    predicate: pii_field_selected       # fires when args.columns intersects PII_FIELDS
                                        # and "pii_authorized" not in execution_context.roles
    description: >
      Block SQL queries that select PII columns unless the agent identity
      carries the pii_authorized role.
```

**Expected behavior:**
- `SELECT id, name FROM users` — allowed; no PII column selected.
- `SELECT id, email FROM users` with role `analyst` — blocked.
- `SELECT id, email FROM users` with role `pii_authorized` — allowed.

**Trace expectation:** Blocked calls produce `fired=True`, `point="PAG"`.
Authorized PII access produces `fired=False` — preserving a full access log
even for permitted calls.

---

## Recipe 3: Procurement spend threshold

**Use case:** A procurement agent that raises purchase orders.  Orders below
$50,000 are within automated authority.  Orders at or above $50,000 must be
blocked.  First-time suppliers (not yet in the approved vendor register) must
be escalated for due diligence even if the amount is small.

**Policy intent:** Hard block for large POs; escalation for unvetted suppliers.

```yaml
constraints:
  - id: block_large_po
    class: hard
    verif: PAG
    response: block
    predicate: po_amount_at_or_above_50k    # fires when args.amount >= 50000
    description: >
      Block purchase orders at or above $50,000. These require manual
      approval outside the agent workflow.

  - id: escalate_first_time_supplier
    class: escalation
    verif: PAG
    response: escalate
    predicate: supplier_not_in_register     # fires when args.vendor not in APPROVED_VENDORS
    description: >
      Escalate POs from first-time or unregistered suppliers for
      procurement due diligence before the order is placed.
```

**Expected behavior:**
- PO for $12,000 from registered vendor — allowed.
- PO for $75,000 from any vendor — blocked (`block_large_po`).
- PO for $3,000 from unregistered vendor — escalated but allowed; escalation
  handler is called for due diligence.
- PO for $60,000 from unregistered vendor — blocked (`block_large_po` fires
  first at PAG because hard constraints are evaluated before escalation
  constraints).

**Trace expectation:** Two separate constraint IDs appear in traces; audit
coverage reports both as evaluated for every PO call.

---

## Recipe 4: Human escalation for sensitive actions

**Use case:** An agent that can perform actions tagged as high-risk in a
capability registry (e.g. `delete_customer_record`, `initiate_wire_transfer`,
`revoke_access`).  These actions should proceed but always trigger a human
review notification.

**Policy intent:** Every call to a high-risk tool fires an escalation to a
human reviewer.  The action is not blocked.

```yaml
constraints:
  - id: escalate_high_risk_action
    class: escalation
    verif: PAG
    response: escalate
    predicate: tool_is_high_risk    # fires when args._risk_level == "high"
                                    # or tool name is in HIGH_RISK_TOOLS registry
    description: >
      Escalate all tool calls tagged as high-risk for asynchronous human
      review. The action proceeds; the escalation handler notifies reviewers.
```

**Expected behavior:**
- `delete_customer_record` — proceeds and returns normally; escalation handler
  receives the `TraceRecord` and notifies the review queue.
- `list_customers` — passes through with no escalation.
- The agent's caller sees no difference in latency or return value.

**Trace expectation:** `fired=True`, `point="PAG"`, `response="escalate"` for
every high-risk call.  The `EscalationRouter` record confirms the handler was
invoked.

---

## Recipe 5: Tool allowlist / denylist

**Use case:** A general-purpose agent that must only use a declared set of
approved tools.  Any call to a tool not in the allowlist — whether injected by
a prompt, hallucinated, or misconfigured — must be blocked before it reaches
the inner toolset.

**Policy intent:** Hard block on any tool name not present in the spec-declared
allowlist.

```yaml
constraints:
  - id: block_tool_not_in_allowlist
    class: hard
    verif: PAG
    response: block_or_escalate
    predicate: tool_name_not_in_allowlist   # fires when ctx["tool"] not in ALLOWED_TOOLS
    description: >
      Block calls to any tool that is not in the declared allowlist.
      Prevents prompt-injection and misconfiguration from reaching
      unintended tools.
```

**Expected behavior:**
- Call to `erp.create_po` (in allowlist) — allowed.
- Call to `os.system` (not in allowlist) — blocked.
- Call to `delegate_to_unknown_agent` (not in allowlist) — blocked.
- Changing `ALLOWED_TOOLS` at runtime and reloading the spec updates enforcement
  without code changes.

**Trace expectation:** One `TraceRecord` per call; `fired=True` for any
disallowed tool, `fired=False` for allowed tools, providing a complete call log.

---

## Recipe 6: Audit-only monitoring mode

**Use case:** A brownfield deployment where a team wants full observability of
every tool call before introducing hard constraints.  No calls should be blocked
or escalated; all activity should be recorded for later policy analysis.

**Policy intent:** Soft post-action constraint that logs every call.  Never
blocks.

```yaml
constraints:
  - id: audit_all_tool_calls
    class: soft
    verif: PAA
    response: log
    predicate: always_true      # fires on every call (predicate always returns True)
    description: >
      Unconditionally log every completed tool call to the trace store.
      Soft/PAA: the action always proceeds; this constraint never blocks.
      Use during a monitoring-only phase before activating hard constraints.
```

**Expected behavior:**
- Every tool call, regardless of outcome, produces a `TraceRecord` with
  `fired=True`, `point="PAA"`, `response="log"`.
- No `ConstraintViolation` is ever raised by this constraint.
- The trace store accumulates a complete call log that can be fed to
  `audit_trace` to identify coverage gaps before tighter policies are added.

**Trace expectation:** 100% call coverage; `audit_trace` I1 (coverage) check
passes for all tools that appear in the trace.

---

## Recipe 7: Customer support refund limits

**Use case:** A customer-support agent authorized to issue refunds up to a
per-transaction limit ($200) and a daily aggregate limit ($1,000).  Refunds
above the per-transaction limit must be blocked.  A soft post-action constraint
accumulates the daily total for reporting.

**Policy intent:** Hard block per-transaction; soft audit for daily aggregate.

```yaml
constraints:
  - id: block_refund_above_authority
    class: hard
    verif: PAG
    response: block_or_escalate
    predicate: refund_exceeds_agent_authority   # fires when args.amount > 200
    description: >
      Block refund requests above $200. Amounts above this threshold
      require supervisor approval and must not be issued by the agent.

  - id: log_daily_refund_total
    class: soft
    verif: PAA
    response: throttle_log
    predicate: tool_is_issue_refund            # fires when tool == "crm.issue_refund"
    description: >
      Log every completed refund to the trace store so the daily aggregate
      can be computed by audit_trace or a downstream reporting job.
```

**Expected behavior:**
- `crm.issue_refund` with `amount=150` — allowed; PAA soft constraint fires and
  logs the record.
- `crm.issue_refund` with `amount=350` — blocked at PAG before the refund is
  issued.
- Daily aggregate reporting reads all `log_daily_refund_total` traces with
  `fired=True` and sums `args.amount`.

**Trace expectation:** Two constraint IDs appear per call.  `block_refund_above_authority`
appears with `fired=True` only for blocked calls; `log_daily_refund_total`
appears with `fired=True` for every completed refund.

---

## Recipe 8: Data export governance

**Use case:** An analytics agent that can export query results to external
destinations.  Small exports (up to 10,000 rows) are routine.  Large exports
above 10,000 rows carry data-exfiltration risk and must be escalated for human
review before the export proceeds.

**Policy intent:** Escalation at PAG for large exports; action proceeds if the
escalation handler approves (or if no synchronous approval gate is wired).

```yaml
constraints:
  - id: escalate_large_data_export
    class: escalation
    verif: PAG
    response: escalate
    predicate: export_row_count_above_threshold   # fires when args.row_limit > 10000
                                                  # or result_set size > 10000
    description: >
      Escalate data export requests that exceed 10,000 rows for human
      review. The export is not automatically blocked; pair with a
      hard constraint reading an approval ledger to gate the action.
```

To turn this into a hard gate (block until a human approves), add a paired hard
constraint:

```yaml
  - id: block_unapproved_large_export
    class: hard
    verif: PAG
    response: block
    predicate: large_export_not_approved   # fires when args.row_limit > 10000
                                           # and export_id not in APPROVAL_LEDGER
    description: >
      Block large exports that have not received explicit approval.
      The approval record is written to APPROVAL_LEDGER by the
      escalation handler after human sign-off.
```

**Expected behavior:**
- Export of 500 rows — allowed; no constraint fires.
- Export of 50,000 rows — escalation handler called; action proceeds (or is
  blocked if the paired hard constraint is active and no approval exists).
- After human approval is recorded in `APPROVAL_LEDGER`, the same export
  call passes the hard constraint.

**Trace expectation:** `escalate_large_data_export` produces `fired=True`,
`point="PAG"`, `response="escalate"`.  If the hard companion is active,
`block_unapproved_large_export` produces `fired=True` when no approval exists
and `fired=False` once approval is recorded.

---

## Next steps

- [docs/integrations.md](integrations.md) — predicate registration API,
  adapter patterns for LangGraph, OpenAI tool calling, AWS Bedrock, and KAOS
  PAIS; how to wire a custom escalation handler to a queue or ticketing system.
- [docs/quickstart-for-developers.md](quickstart-for-developers.md) — install,
  write your first spec, wrap your first toolset, and run `audit_trace` in five
  minutes.
