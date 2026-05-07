"""SARC ExecutionContext — typed identity bag for governance events.

A small, framework-agnostic dataclass capturing the *who/where/why* metadata
that should accompany every governance evaluation. Production deployments
typically need at minimum:

- ``principal_id``  — the human or service identity authorising the action
- ``agent_id``      — the agent / loop that produced the tool call
- ``tenant_id``     — multi-tenant isolation key (if applicable)
- ``session_id``    — correlation key for trace persistence
- ``roles``         — RBAC role list, used by your own predicates
- ``environment``   — ``"prod"``, ``"staging"``, etc.
- ``request_id``    — upstream / inbound request correlation id
- ``metadata``      — open-ended extension dict

The library does not enforce any policy on these fields — predicates and
escalation handlers are free to consult them. The dataclass exists so that
the *shape* is canonical across adapters, traces, and audit reports.

The class is intentionally permissive: every field has a default. Adapters
for LangGraph / Bedrock / OpenAI tool calling can build an
``ExecutionContext`` from whatever their framework gives them via
:meth:`from_obj` or :meth:`from_mapping`.

This module is **backward compatible**: existing ``GovernanceToolset``
callers that pass a framework-native ``ctx`` continue to work. To opt in,
either pass an ``ExecutionContext`` directly as ``ctx``, or attach one as
``ctx.execution_context`` / ``ctx.deps.execution_context``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Mapping, Tuple


@dataclass
class ExecutionContext:
    """Canonical identity / environment context for a single governed call.

    All fields are optional so an ``ExecutionContext()`` is always valid;
    populate the ones your deployment cares about.
    """

    principal_id: str = ""
    agent_id: str = ""
    tenant_id: str = ""
    session_id: str = ""
    roles: Tuple[str, ...] = ()
    environment: str = ""
    request_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ExecutionContext":
        """Build from a dict-like, ignoring unknown keys.

        Unknown keys land in :attr:`metadata` so adapters can pass through
        framework-specific fields without losing them.
        """
        known = {f for f in cls.__dataclass_fields__}
        kwargs: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        for k, v in data.items():
            if k in known and k != "metadata":
                kwargs[k] = v
            elif k == "metadata" and isinstance(v, Mapping):
                kwargs["metadata"] = dict(v)
            else:
                extras[k] = v
        # Coerce roles to tuple if a list was passed
        if "roles" in kwargs and isinstance(kwargs["roles"], (list, tuple)):
            kwargs["roles"] = tuple(kwargs["roles"])
        ctx = cls(**kwargs)
        if extras:
            ctx.metadata.update(extras)
        return ctx

    @classmethod
    def from_obj(cls, obj: Any) -> "ExecutionContext":
        """Best-effort extraction from a framework context object.

        Looks for an attached ``execution_context`` attribute first
        (recommended), then for a ``deps.execution_context``, then attempts
        to read fields directly off the object. Returns an empty
        ``ExecutionContext`` if nothing was found.
        """
        if obj is None:
            return cls()
        if isinstance(obj, ExecutionContext):
            return obj

        # 1. ctx.execution_context
        ec = getattr(obj, "execution_context", None)
        if isinstance(ec, ExecutionContext):
            return ec
        if isinstance(ec, Mapping):
            return cls.from_mapping(ec)

        # 2. ctx.deps.execution_context
        deps = getattr(obj, "deps", None)
        if deps is not None:
            ec = getattr(deps, "execution_context", None)
            if isinstance(ec, ExecutionContext):
                return ec
            if isinstance(ec, Mapping):
                return cls.from_mapping(ec)

        # 3. Direct attribute scrape (best-effort).
        scraped: Dict[str, Any] = {}
        for fname in cls.__dataclass_fields__:
            if fname == "metadata":
                continue
            v = getattr(obj, fname, None)
            if v is None and deps is not None:
                v = getattr(deps, fname, None)
            if v is not None:
                scraped[fname] = v
        if scraped:
            return cls.from_mapping(scraped)
        return cls()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly dict (roles as a list)."""
        d = asdict(self)
        d["roles"] = list(self.roles)
        return d

    def is_empty(self) -> bool:
        """Return True if no identifying fields are populated."""
        return (
            not self.principal_id
            and not self.agent_id
            and not self.tenant_id
            and not self.session_id
            and not self.roles
            and not self.environment
            and not self.request_id
            and not self.metadata
        )


__all__ = ["ExecutionContext"]
