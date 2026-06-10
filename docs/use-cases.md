# POC use cases

The constraint model is general; these are the kinds of tasks the demo and tests
cover and that fit naturally into the PAG/ATM/PAA structure:

- **Procurement approval** — block POs above a threshold (hard/PAG), route first-time
  suppliers for review (escalation/PAG), flag rolling-spend overages (soft/PAA).
  Implemented end-to-end in [`examples/procurement_agent/`](../examples/procurement_agent/README.md).
- **Data access** — block queries that select restricted columns (hard/PAG),
  log queries returning > N rows for review (soft/PAA), escalate cross-tenant access
  attempts (escalation/PAG).
- **Customer refunds** — block refunds above an agent's authority (hard/PAG),
  escalate refunds for VIP accounts (escalation/PAG), track cumulative daily refund
  volume per agent (soft/PAA).
- **Incident response / runbooks** — block destructive actions on production hosts
  outside a maintenance window (hard/PAG), escalate any action against a tagged
  "critical" host (escalation/PAG), audit elapsed time on long-running remediations
  (soft/ATM via the `elapsed` field).

In each case the agent code is unchanged; only the `ConstraintSpec` differs.
