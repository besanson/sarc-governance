"""SARC GovernanceToolset — framework-adapter-friendly wrapper.

This module is intentionally **framework-agnostic**: no specific agent
framework is imported.  It defines two lightweight ``Protocol`` types:

- ``ToolsetProtocol``: any async toolset with a ``call_tool`` method.
- ``MemoryProtocol``: any session memory that can persist events.

``GovernanceToolset`` wraps any ``ToolsetProtocol`` and enforces SARC
constraints at three in-process enforcement points:

- **PAG** (Pre-Action Gate) — before the inner toolset is called.
  Hard and escalation constraints are evaluated on ``(tool, args)``.
  A fired hard constraint raises ``ConstraintViolation`` *without*
  calling the inner toolset.  A fired escalation routes to the ER.

- **ATM** (Action-Time Monitor) — the inner toolset call is measured;
  hard and escalation constraints evaluated on
  ``(tool, args, result, elapsed)``.
  A fired hard constraint raises *after* the call returns (result is lost
  to the caller but the trace records the event).

- **PAA** (Post-Action Auditor) — after the call completes.
  Soft and escalation constraints are evaluated on ``(tool, args, result)``.
  Fired escalation constraints route to the ER; soft constraints log only.

Every evaluation produces a ``TraceRecord`` which is persisted via
``MemoryProtocol.add_event`` if a memory and session_id are supplied.

Zero-adapter case
-----------------
Any toolset whose ``call_tool(name, args, ctx, tool)`` method is async
already satisfies ``ToolsetProtocol``. Pass it directly::

    toolset = GovernanceToolset(wrapped=my_async_toolset, spec=spec)

Adapting to any other framework
---------------------------------
Implement ``ToolsetProtocol`` and pass an instance as ``wrapped``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, runtime_checkable

from sarc_governance.constraints import ConstraintClass, ConstraintSpec, EnforcementPoint, Response
from sarc_governance.context import ExecutionContext
from sarc_governance.escalation import EscalationRouter
from sarc_governance.trace import TraceRecord, new_action_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols — the only surface this module depends on externally
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolsetProtocol(Protocol):
    """Structural type for any async toolset.

    Only the ``call_tool`` method is required.  The signature mirrors
    pydantic-ai's ``AbstractToolset.call_tool`` but omits the framework-
    specific ``ctx`` and ``tool`` arguments (which become ``Any``).
    """

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        ...


@runtime_checkable
class MemoryProtocol(Protocol):
    """Minimal memory interface for persisting governance events."""

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        ...


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ConstraintViolation(Exception):
    """Raised when a ``hard`` constraint blocks tool execution at PAG or ATM."""

    def __init__(self, constraint_id: str, point: EnforcementPoint, message: str = ""):
        self.constraint_id = constraint_id
        self.point = point
        super().__init__(message or f"Constraint {constraint_id!r} blocked at {point.value}")


# ---------------------------------------------------------------------------
# GovernanceToolset
# ---------------------------------------------------------------------------


@dataclass
class GovernanceToolset:
    """Wraps any ``ToolsetProtocol`` and enforces SARC constraints.

    Parameters
    ----------
    wrapped:
        The inner toolset to delegate to after passing enforcement gates.
    spec:
        The ``ConstraintSpec`` driving enforcement.
    router:
        ``EscalationRouter`` for fired escalation events.  Defaults to a
        log-only router.
    memory_getter:
        Optional callable ``(ctx) -> MemoryProtocol | None``.  Called on
        every invocation to retrieve the current memory backend.  Useful
        when memory is embedded in an ``AgentDeps``-style object or similar.
    session_id_getter:
        Optional callable ``(ctx) -> str``.  Extracts the session id from
        the context object.
    """

    wrapped: ToolsetProtocol
    spec: ConstraintSpec = field(default_factory=ConstraintSpec)
    router: EscalationRouter = field(default_factory=EscalationRouter)
    memory_getter: Optional[Callable[[Any], Optional[MemoryProtocol]]] = field(default=None)
    session_id_getter: Optional[Callable[[Any], str]] = field(default=None)
    context_getter: Optional[Callable[[Any], Optional[ExecutionContext]]] = field(default=None)
    stamp_context: bool = field(default=True)
    _action_seq: int = field(default=0, repr=False, compare=False)
    _action_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Public call_tool — the single entry point
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        name: str,
        tool_args: Dict[str, Any],
        ctx: Any = None,
        tool: Any = None,
    ) -> Any:
        """Enforce SARC constraints around a single tool invocation.

        Parameters
        ----------
        name:
            Tool name (used in predicate context and trace records).
        tool_args:
            Tool arguments dict.
        ctx:
            Framework context object (e.g. a ``RunContext[AgentDeps]``-style
            object). Passed unchanged to the inner toolset.
        tool:
            Framework tool descriptor.  Passed unchanged to the inner toolset.
        """
        action_id = await self._next_action_id()
        execution_context = self._resolve_context(ctx)
        pag_ctx: Dict[str, Any] = {"tool": name, "args": tool_args}
        if execution_context is not None and not execution_context.is_empty():
            pag_ctx["execution_context"] = execution_context

        # ---- PAG -------------------------------------------------------
        for c in self.spec.at(EnforcementPoint.PAG):
            fired = bool(c.predicate(pag_ctx))
            rec = TraceRecord(
                action_id=action_id,
                tool=name,
                point=EnforcementPoint.PAG,
                constraint_id=c.id,
                klass=c.klass,
                fired=fired,
                response=c.response,
                extra=self._stamp(execution_context),
            )
            await self._emit(ctx, rec)
            if fired:
                if c.klass == ConstraintClass.HARD or c.response in (
                    Response.BLOCK,
                    Response.BLOCK_OR_ESCALATE,
                    Response.SUSPEND_ROUTE_DEFAULT_DENY,
                ):
                    await self.router.route(rec, pag_ctx)
                    raise ConstraintViolation(c.id, EnforcementPoint.PAG)
                if c.klass == ConstraintClass.ESCALATION:
                    await self.router.route(rec, pag_ctx)

        # ---- ATM -------------------------------------------------------
        atm_constraints = self.spec.at(EnforcementPoint.ATM)
        started = time.perf_counter()
        # Any exception from the inner toolset propagates; PAA is skipped.
        result = await self.wrapped.call_tool(name, tool_args, ctx, tool)
        elapsed = time.perf_counter() - started

        atm_ctx = {"tool": name, "args": tool_args, "result": result, "elapsed": elapsed}
        if execution_context is not None and not execution_context.is_empty():
            atm_ctx["execution_context"] = execution_context
        for c in atm_constraints:
            fired = bool(c.predicate(atm_ctx))
            rec = TraceRecord(
                action_id=action_id,
                tool=name,
                point=EnforcementPoint.ATM,
                constraint_id=c.id,
                klass=c.klass,
                fired=fired,
                response=c.response,
                extra={"elapsed": elapsed, **self._stamp(execution_context)},
            )
            await self._emit(ctx, rec)
            if fired and c.klass == ConstraintClass.HARD:
                await self.router.route(rec, atm_ctx)
                raise ConstraintViolation(c.id, EnforcementPoint.ATM)
            if fired and c.klass == ConstraintClass.ESCALATION:
                await self.router.route(rec, atm_ctx)

        # ---- PAA -------------------------------------------------------
        paa_ctx = {"tool": name, "args": tool_args, "result": result}
        if execution_context is not None and not execution_context.is_empty():
            paa_ctx["execution_context"] = execution_context
        for c in self.spec.at(EnforcementPoint.PAA):
            fired = bool(c.predicate(paa_ctx))
            rec = TraceRecord(
                action_id=action_id,
                tool=name,
                point=EnforcementPoint.PAA,
                constraint_id=c.id,
                klass=c.klass,
                fired=fired,
                response=c.response,
                extra=self._stamp(execution_context),
            )
            await self._emit(ctx, rec)
            if fired and c.klass == ConstraintClass.ESCALATION:
                await self.router.route(rec, paa_ctx)
            if fired and c.klass == ConstraintClass.SOFT:
                logger.info(
                    "PAA soft constraint fired: %s for tool=%s action=%s",
                    c.id,
                    name,
                    action_id,
                )

        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _next_action_id(self) -> str:
        async with self._action_lock:
            self._action_seq += 1
            return f"act-{self._action_seq}"

    def _stamp(self, ec: Optional[ExecutionContext]) -> Dict[str, Any]:
        """Return a fresh extra-dict containing the execution context, or empty."""
        if not self.stamp_context or ec is None or ec.is_empty():
            return {}
        return {"execution_context": ec.to_dict()}

    def _resolve_context(self, ctx: Any) -> Optional[ExecutionContext]:
        """Resolve an ExecutionContext for this call, or None."""
        if self.context_getter is not None:
            try:
                ec = self.context_getter(ctx)
            except Exception:
                logger.exception("governance: context_getter raised; ignoring")
                ec = None
            if isinstance(ec, ExecutionContext):
                return ec
            if ec is None:
                return None
        return ExecutionContext.from_obj(ctx) if ctx is not None else None

    async def _emit(self, ctx: Any, rec: TraceRecord) -> None:
        """Persist a trace record on the agent's memory if available."""
        memory: Optional[MemoryProtocol] = None
        session_id: str = ""

        if self.memory_getter is not None:
            memory = self.memory_getter(ctx)

        if memory is None and ctx is not None:
            # AgentDeps-style auto-detection: ctx.deps.memory / ctx.deps.session_id
            deps = getattr(ctx, "deps", None)
            if deps is not None:
                memory = getattr(deps, "memory", None)
                session_id = getattr(deps, "session_id", "") or ""

        if self.session_id_getter is not None:
            session_id = self.session_id_getter(ctx) or session_id

        if memory is None or not session_id:
            return

        try:
            await memory.add_event(session_id, "governance_event", rec.to_dict())
        except Exception:
            # Audit emission must never break the agent loop.
            logger.exception(
                "governance: failed to persist trace record for constraint=%s action=%s",
                rec.constraint_id,
                rec.action_id,
            )


__all__ = [
    "ConstraintViolation",
    "GovernanceToolset",
    "MemoryProtocol",
    "ToolsetProtocol",
]
