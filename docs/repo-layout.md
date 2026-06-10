# Repository layout

| Path | Contents |
|---|---|
| [`src/sarc_governance/`](../src/sarc_governance/) | Core package: constraints, governance, escalation, audit, trace, specs, predicates, CLI, context, policy, hashchain, stores |
| [`src/sarc_governance/adapters/`](../src/sarc_governance/adapters/) | Optional framework adapters: `pais.py` — `PAISContextMapper`, `PAISMemoryGuard`, `SARCGovernanceToolset`, `create_governed_agent_server`, `build_governed_toolset` |
| [`docs/`](.) | Architecture, spec authoring, audit, integrations, pre-production checklist, policy lifecycle, trace stores, security model, failure modes, production-hardening |
| [`examples/procurement_agent/`](../examples/procurement_agent/README.md) | End-to-end demo with a mock ERP toolset and YAML spec |
| [`examples/audit_trace_file/`](../examples/audit_trace_file/README.md) | Spec + pass/fail trace JSON for the `sarc-governance audit` CLI |
| [`examples/preproduction_trace_store/`](../examples/preproduction_trace_store/README.md) | SQLite trace store + hash chain + policy diff demo |
| [`examples/human_escalation/`](../examples/human_escalation/README.md) | approve / deny / timeout pattern for human-in-the-loop |
| [`examples/multi_agent_governed/`](../examples/multi_agent_governed/run_demo.py) | Two governed agents chained — coordinator + validator with independent specs; shows constraint propagation across an agent boundary |
| [`examples/kaos_pais_adapter/`](../examples/kaos_pais_adapter/adapter.py) | Adapter for [KAOS](https://github.com/axsaucedo/kaos) — wraps `DelegationToolset` using `sarc_governance.adapters.pais`; demo uses stand-in PAIS types (no `pais` package required) |
| [`examples/mcp_tool_governance/`](../examples/mcp_tool_governance/run_demo.py) | MCP tool governance — allow, block, and escalate across three constraint classes; stub MCPToolset, no external API keys required |
| [`examples/langgraph_style_adapter/`](../examples/langgraph_style_adapter/README.md) | Wrap a LangGraph-shaped tools node (no `langgraph` dependency) |
| [`examples/openai_tool_calling_adapter/`](../examples/openai_tool_calling_adapter/README.md) | Wrap OpenAI-style function dispatch (no `openai` dependency) |
| [`examples/bedrock_action_group_adapter/`](../examples/bedrock_action_group_adapter/README.md) | Wrap an AWS Bedrock Agent action-group Lambda handler (no `boto3` dependency) |
| [`benchmarks/`](../benchmarks/README.md) | Pre-computed SARC paper evaluation results and the script that produced them |
| [`paper/`](../paper/README.md) | LaTeX source for the SARC paper |
| [`tests/`](../tests/) | pytest suite covering specs, governance, audit, escalation, predicates, trace, CLI, examples |
