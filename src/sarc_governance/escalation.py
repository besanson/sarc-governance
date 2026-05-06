"""SARC Escalation Router (paper §4.1, ER).

The ``EscalationRouter`` is a stateless dispatcher that receives fired
``TraceRecord`` events and routes them to a pluggable async handler.

Default behaviour: structured ``WARNING`` log.  Deployments replace the
handler with something that pages a human operator, opens a ticket, or
writes to an external review queue.  The router *never decides* — it only
routes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from sarc_governance.trace import TraceRecord

logger = logging.getLogger(__name__)

EscalationHandler = Callable[[TraceRecord, Dict[str, Any]], Awaitable[None]]


async def _default_handler(record: TraceRecord, ctx: Dict[str, Any]) -> None:
    """Log-only default escalation handler."""
    logger.warning(
        "ER escalation: constraint=%s point=%s tool=%s action=%s response=%s fired=%s",
        record.constraint_id,
        record.point.value,
        record.tool,
        record.action_id,
        record.response.value,
        record.fired,
    )


@dataclass
class EscalationRouter:
    """Routes fired constraint events to a pluggable async handler.

    Parameters
    ----------
    handler:
        Optional async callable ``(record, ctx) -> None``.  If ``None``,
        the default structured-log handler is used.

    Example
    -------
    ::

        async def my_handler(record: TraceRecord, ctx: dict) -> None:
            await ticket_system.open(record.constraint_id, ctx)

        router = EscalationRouter(handler=my_handler)
    """

    handler: Optional[EscalationHandler] = field(default=None)

    async def route(self, record: TraceRecord, ctx: Dict[str, Any]) -> None:
        """Dispatch *record* to the configured handler (or the default one)."""
        fn: EscalationHandler = self.handler if self.handler is not None else _default_handler
        try:
            await fn(record, ctx)
        except Exception:
            # Escalation routing must never break the calling agent loop.
            logger.exception(
                "ER: handler raised for constraint=%s action=%s — suppressed",
                record.constraint_id,
                record.action_id,
            )


__all__ = [
    "EscalationHandler",
    "EscalationRouter",
]
