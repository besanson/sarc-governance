# Threat Model

SARC is a runtime governance layer, not a security boundary. This document states what SARC protects against, what it does not protect against, and the assumptions a deploying organisation must satisfy for the protections to hold.

## What SARC helps with

- **Accidental policy violations**: constraints evaluated at PAG prevent governed tools from being called with arguments that violate declared policy, before the call is dispatched.
- **Missing audit records**: every constraint evaluation emits a TraceRecord; the trace store captures a full record of constraint outcomes for every action.
- **Cross-tenant access mistakes**: an escalation or hard constraint can compare actor.tenant_id to resource.tenant_id and block or route cross-tenant calls before they reach the downstream system.
- **Escalation handler failures**: handler exceptions are caught and logged; a broken delivery target never converts a hard block into a pass.
- **Soft-window overages**: a soft/PAA constraint can observe rolling state (spend, row counts, call frequency) and emit audit records or throttle.

## What SARC does not protect against

- **Malicious policy authors**: predicates are arbitrary Python callables evaluated in-process. A malicious spec is arbitrary code. Treat ConstraintSpec as code, not data, when loading from untrusted sources; use safe_load_spec for file paths only.
- **Compromised runtime environment**: if the process, OS, or container is compromised, constraint evaluation can be bypassed outside SARC's control.
- **Direct database tampering**: trace stores write to files or SQLite; the hash chain is tamper-evident but not tamper-proof. Direct file modification outside the library is not detected until verify-chain is run.
- **Arbitrary code execution in the host application**: SARC does not sandbox the agent, the model, or the application code that constructs tool arguments.
- **Prompt injection by itself**: SARC does not parse or filter model outputs. Prompt injection can be mitigated only if it is paired with hard constraints on tool names and argument shapes.
- **Distributed transaction semantics**: SARC does not coordinate writes across multiple agents or processes. If two agents call the same downstream service concurrently, SARC does not arbitrate.
- **Authentication and authorization**: SARC does not authenticate callers or authorize access to tools. It enforces declared constraints on tool calls; it does not replace IAM.

## Trusted components

- The ConstraintSpec and its predicates (treat as code, not data)
- The process environment (OS, container, Python interpreter)
- The TraceStore backend (files, SQLite, or user-supplied)
- The EscalationRouter handler implementation

## Untrusted or semi-trusted components

- Tool arguments (user-supplied or model-generated — validate at PAG)
- The execution context (agent_id, tenant_id — should come from authenticated infrastructure, not model output)
- The downstream toolset (SARC calls it; it may have its own failure modes)

## Policy author assumptions

- Predicates are correct: a mispredicate that always returns False is a silent governance gap.
- Constraint IDs are stable: renaming a constraint ID breaks audit_trace coverage checks against historical traces.
- Spec approval is enforced by the deploying organisation's CI/CD: SARC's PolicyMetadata.approval_status is a string; enforcement is the deployer's responsibility.

## Trace integrity assumptions

- Single writer per trace file: the shipped stores (JSONL, SQLite) are single-writer. Concurrent writers are not safe without a mutex at the application level.
- Hash chain integrity requires continuous appending: the chain covers records in append order. A record removed from the middle breaks the chain from that point forward.
- verify-chain detects tampering only when the chain is enabled (hash_chain=True at store construction).

## Handler failure assumptions

- Escalation handlers are best-effort delivery: a failed handler does not block constraint evaluation or prevent trace emission. Failed deliveries are logged.
- A hard constraint that fires and raises ConstraintViolation does so regardless of handler success.

## Example risks and mitigations

| Risk | Mitigation |
|---|---|
| Model-generated tool args bypass a hard constraint | Review predicate coverage; add negative tests with adversarial args |
| Trace store fills disk | Monitor file size; rotate or export to a remote store |
| Escalation handler is unreachable | Design handler to be idempotent and queue-backed; SARC logs on failure |
| Policy spec loaded from user-supplied URL | Use safe_load_spec (file paths only); never pass user input to load_spec with extra_predicates |
| Cross-agent authority escalation | Use ExecutionContext.roles and authority intersection at each agent boundary |
