# Policy lifecycle

The `sarc_governance.policy` module adds three primitives on top of the
spec model:

- `PolicyMetadata` — descriptive fields (id, version, owner, approval
  status, etc.) that travel alongside a `ConstraintSpec`.
- `policy_checksum(spec)` — SHA-256 over the canonical shape of the
  spec.
- `inspect_policy(spec)` and `diff_policies(old, new)` — structured
  views suitable for CLI / CI / docs.

These primitives let you *describe* a lifecycle in your CI/CD; the
library does **not** enforce one. In particular:

- `approval_status` is a string. The library validates it is one of
  `draft / in_review / approved / deprecated` but does not check
  signatures or talk to an approval system.
- The checksum is a content fingerprint, not a signature. It tells you
  whether a spec changed; it does not tell you who changed it or whether
  they were authorised.

To actually enforce "only approved specs may run":

```python
from sarc_governance import load_spec, PolicyMetadata, policy_checksum

spec = load_spec("config/spec.yaml")
meta = PolicyMetadata(
    policy_id="procurement",
    version="2.4.1",
    approved_by="security@example.com",
    approval_status="approved",
    checksum="<value pinned in your release pipeline>",
)
if meta.approval_status != "approved":
    raise SystemExit("refusing to load non-approved spec")
if meta.checksum and meta.checksum != policy_checksum(spec):
    raise SystemExit("spec checksum drift — refusing to load")
```

The pinning step happens in your release pipeline: compute the checksum
when the PR merges, write it into a metadata file (or the deployment
config), and refuse to load if it drifts at runtime.

## Checksum stability

The checksum is computed over a canonical view of each constraint:

- `id`, `class`, `verif`, `response`, `description`, and the predicate's
  `__name__` (or `__qualname__`).

It is **stable** across:

- YAML/JSON formatting differences (indentation, quoting).
- Constraint ordering in the source file.
- Re-instantiating the same registered predicate by name.

It **changes** when:

- Any of the canonical fields change.
- A predicate is renamed or replaced with a different registered name.

Anonymous lambdas all hash as `<lambda>`, so they do not contribute
identity to the checksum. Register predicates by name when stability
across processes matters.

## CI integration

```yaml
- name: Inspect policy
  run: sarc-governance policy inspect config/spec.yaml --json > policy.json

- name: Diff against base branch
  run: |
    git show origin/main:config/spec.yaml > /tmp/old.yaml
    sarc-governance policy diff /tmp/old.yaml config/spec.yaml --exit-code
```

`--exit-code` causes `policy diff` to return non-zero on any change,
which is convenient as a "force a human reviewer to confirm intent"
gate.

## What this is *not*

This module is not a substitute for:

- A **signed release artefact** (use Sigstore, GPG, or your platform's
  signing).
- A **policy-as-code review tool** (Conftest / OPA bundle tests).
- A **detection system** for adversarial spec edits at rest — that
  needs immutable storage or an external audit log.

It is the minimum metadata + content fingerprint needed to wire those
systems in.
