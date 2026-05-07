# Security policy

## Supported versions

`sarc-governance` is pre-1.0. Security fixes are applied to the latest
commit on `main` only.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Email the maintainer directly (see the GitHub profile) with:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

You will receive a response within 5 business days. If the issue is confirmed,
a fix will be released as soon as practical and you will be credited in the
changelog unless you prefer otherwise.

## Known limitations

See [docs/security-model.md](docs/security-model.md) for the full threat model,
including what the library explicitly does and does not protect against.

Key points:
- Predicates are arbitrary Python callables — use `safe_load_spec` in production
  to restrict loading to registry-only predicates.
- The hash chain is tamper-evident, not tamper-proof.
- The default escalation router logs only — wire a real handler before shipping.
- Single-writer trace stores — not suitable for multi-process deployments without
  a custom `TraceStore` backend.
