# How SARC relates to other approaches

| Approach | What it does well | Gap SARC addresses |
|---|---|---|
| Plain logging | Records events after they happen | Does not enforce before tool execution |
| Tool allowlists | Restricts available tools | Usually lacks contextual policy decisions |
| LLM output guardrails | Filters model inputs/outputs | May not govern concrete tool-call arguments |
| Framework callbacks | Hooks into agent execution | Often framework-specific; not audit-centric |
| General policy engines (OPA, Cedar) | Express rich policies | May not provide agent/tool trace semantics |
| SARC | Runtime action governance + typed audit traces | Early-stage developer toolkit; not production-hardened |

SARC complements rather than replaces these controls. Logging is still useful. IAM still owns
authentication. Model-level guardrails still filter outputs. SARC adds the enforcement loop and
the audit trail at the tool-dispatch boundary.
