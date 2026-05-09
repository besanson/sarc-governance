"""sarc_governance.adapters — optional framework-specific adapter helpers.

Each submodule in this package provides helpers for a specific agent framework.
None are imported at package load time; import the one you need explicitly.

Available adapters
------------------
- :mod:`sarc_governance.adapters.pais` — KAOS PAIS / DelegationToolset helpers:
  ``PAISContextMapper``, ``PAISMemoryGuard``, ``build_governed_toolset``.
"""
