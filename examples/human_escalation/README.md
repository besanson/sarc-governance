# Human-in-the-loop escalation

A runnable, dependency-free demo that shows how to wire a human reviewer
into a SARC-governed tool call. Three outcomes are exercised:

| Scenario | Reviewer says | Result |
|---|---|---|
| Approved refund | `approve` | tool runs |
| Denied refund | `deny` | hard constraint blocks |
| Timed-out refund | (no response) | default-deny: hard constraint blocks |

## How it stays honest about SARC

`EscalationRouter` is the *router*, not the *decider*. SARC does not change
that. Real gating is done by a paired pattern:

1. An **escalation/PAG** constraint (`ce_needs_review`) fires on the
   condition that requires review and routes the event through the router.
   The handler awaits the reviewer and writes the decision to an out-of-band
   approval ledger.
2. A **hard/PAG** constraint (`ch_blocked_unless_approved`) reads the
   ledger. It fires (and blocks) for the same condition unless the ledger
   records an explicit `"approve"`.

This keeps the SARC layer's contract intact: hard means hard; escalation
just routes a fired event somewhere asynchronous.

## Run

```bash
python examples/human_escalation/run_demo.py
```

Expected output:

```
============================================================
Human-in-the-Loop Escalation Demo
============================================================
  Approved refund                     review=approve  -> EXECUTED
  Denied refund                       review=deny     -> BLOCKED (ch_blocked_unless_approved)
  Timed-out refund (default-deny)     review=timeout  -> BLOCKED (ch_blocked_unless_approved)
```

## Adapting to a real reviewer

Replace `DeterministicReviewer.review` with whatever your queue/ticket/IM
backend exposes. The contract is one async function that returns one of
`"approve"`, `"deny"`, or `"timeout"` (or anything that is not `"approve"`,
which the ledger treats as a denial). The wrapping `asyncio.wait_for`
provides the deadline that gives "timeout" its meaning.

The handler also filters by `record.constraint_id`: the paired hard
constraint flows through the router for telemetry but must not consume
another reviewer round.
