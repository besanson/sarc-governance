"""Stub for pais.tools — minimal DelegationToolset for SARC integration tests."""

from __future__ import annotations

from typing import Any, Dict, List


class DelegationToolset:
    """Stub matching the real pais DelegationToolset call_tool interface.

    Dispatches calls to registered sub-agents by matching tool name to
    sub-agent name (or the ``delegate_to_{name}`` prefix convention).
    """

    def __init__(self, sub_agents: List[Any]) -> None:
        self._agents: Dict[str, Any] = {a.name: a for a in sub_agents}

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        # Support both bare name ("echo") and prefixed ("delegate_to_echo").
        agent_name = name.removeprefix("delegate_to_")
        agent = self._agents.get(agent_name)
        if agent is None:
            raise ValueError(f"pais stub: unknown sub-agent {name!r}")
        task = tool_args.get("task", "")
        return await agent.process_message(task, {})
