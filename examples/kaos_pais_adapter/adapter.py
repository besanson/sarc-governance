"""KAOS PAIS × SARC Governance adapter (example wrapper).

The canonical production implementation is now in the library:

    sarc_governance.adapters.pais.build_governed_toolset

This module re-exports it unchanged for backwards compatibility.
New deployments should import directly from the library:

    from sarc_governance.adapters.pais import build_governed_toolset

Why the library version is preferred
-------------------------------------
- Includes :class:`~sarc_governance.adapters.pais.PAISContextMapper` for
  explicit tenant / role / principal-id mapping from ``AgentDeps``.
- Includes :class:`~sarc_governance.adapters.pais.PAISMemoryGuard` (enabled by
  default via ``guard_memory=True``) to prevent silent trace drops when the
  PAIS session has not been created before ``add_event`` is called.
- Covered by the library test suite (``tests/test_pais_adapter.py``).

Typical usage
-------------
::

    from sarc_governance.adapters.pais import build_governed_toolset
    from sarc_governance.specs import load_spec

    spec    = load_spec("/config/sarc_spec.yaml")
    toolset = build_governed_toolset(
        delegation_toolset=DelegationToolset(sub_agents, memory, session_id),
        agent_name=settings.agent_name,
        tenant_id=settings.tenant_id,
        spec=spec,
    )
    # Use ``toolset`` wherever PAIS previously used ``DelegationToolset``.

See ``docs/pais-integration.md`` for the full integration guide.
"""

from sarc_governance.adapters.pais import build_governed_toolset  # noqa: F401

__all__ = ["build_governed_toolset"]
