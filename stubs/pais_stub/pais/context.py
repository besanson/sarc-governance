"""Stub for pais.context — minimal AgentDeps for SARC integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Tuple


@dataclass
class AgentDeps:
    """Stub matching the pais AgentDeps shape that GovernanceToolset auto-detects."""

    memory: Any
    session_id: str
    tenant_id: str = ""
    roles: Tuple[str, ...] = field(default_factory=tuple)
    principal_id: str = ""
