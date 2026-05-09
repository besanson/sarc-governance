# MCP Tool Governance Example

Demonstrates how to govern MCP-style tools using SARC's adapter pattern — allow, block, and escalate across three constraint classes, with no external API keys or MCP server required.

## What this shows

| Scenario | Tool | Constraint | Outcome |
|---|---|---|---|
| 1 | `read_file` | — | ALLOW |
| 2 | `execute_shell` | `block_shell_execution` (hard, PAG) | BLOCK → `ConstraintViolation` |
| 3 | `write_file /etc/hosts` | `escalate_sensitive_filesystem_write` (escalation, PAG) | ESCALATE → ER; execution continues |
| 4 | `send_email` | `log_email_sends` (soft, PAA) | ALLOW + soft audit log |
| 5 | `write_file /tmp/…` | — | ALLOW |
| 6 | Direct call (ungoverned) | — | bypasses SARC entirely |

Scenario 6 is intentional: it illustrates that SARC governs **only tool boundaries explicitly wrapped** by the `GovernanceToolset`. MCP tools called outside the wrapper are not governed.

## Run

```bash
python examples/mcp_tool_governance/run_demo.py
```

No dependencies beyond `sarc-governance` itself.

## Key files

- `run_demo.py` — stub MCPToolset, constraint spec, escalation handler, and five governed + one ungoverned scenario.

## Adapting to a real MCP client

Replace `MCPToolset` with a class that wraps your actual MCP client:

```python
class RealMCPToolset:
    def __init__(self, client):
        self._client = client

    async def call_tool(self, name, tool_args, ctx, tool):
        return await self._client.call_tool(name, tool_args)

governed = GovernanceToolset(wrapped=RealMCPToolset(my_mcp_client), spec=spec)
```

The adapter pattern and constraint spec are identical. See [`docs/mcp-tool-governance.md`](../../docs/mcp-tool-governance.md) for the full integration guide.
