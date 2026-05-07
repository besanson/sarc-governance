"""Built-in escalation handlers for common delivery targets.

Each handler is an async callable that satisfies ``EscalationHandler``::

    async def handler(record: TraceRecord, ctx: dict) -> None: ...

Import and pass to ``EscalationRouter``::

    from sarc_governance.handlers import WebhookEscalationHandler
    from sarc_governance import EscalationRouter

    router = EscalationRouter(
        handler=WebhookEscalationHandler(
            url="https://your-webhook-endpoint/escalations",
            headers={"Authorization": "Bearer <token>"},
        )
    )

Handlers must never raise — failures are logged and swallowed so that a
broken delivery target never converts a hard block into a pass.  Retries
are the responsibility of the receiving infrastructure (queue, webhook
relay, etc.).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict

from sarc_governance.trace import TraceRecord

logger = logging.getLogger(__name__)


@dataclass
class WebhookEscalationHandler:
    """POST escalation events as JSON to an HTTP/HTTPS endpoint.

    Parameters
    ----------
    url:
        The endpoint that receives escalation payloads.  Must accept
        ``Content-Type: application/json`` POST requests.
    headers:
        Additional HTTP headers (e.g. ``{"Authorization": "Bearer <token>"}``,
        ``{"X-Api-Key": "..."}``, Slack/Teams webhook tokens, etc.).
    timeout:
        Request timeout in seconds.  Defaults to 5.  The agent loop is
        blocked for at most this long on escalation delivery.

    Payload shape
    -------------
    ::

        {
          "constraint_id": "block_high_value_action",
          "point":         "PAG",
          "tool":          "erp.create_po",
          "action_id":     "act-3",
          "klass":         "hard",
          "response":      "block_or_escalate",
          "fired":         true,
          "execution_context": { ... },   // present when GovernanceToolset
                                          // has a context_getter
          "predicate_context": { ... }    // the ctx dict at the enforcement
                                          // point (tool, args, result, …)
        }

    Examples
    --------
    Slack incoming webhook::

        WebhookEscalationHandler(url="https://hooks.slack.com/services/...")

    Generic HTTPS endpoint with auth::

        WebhookEscalationHandler(
            url="https://api.example.com/governance/escalations",
            headers={"Authorization": "Bearer secret"},
        )

    Internal sidecar (no auth)::

        WebhookEscalationHandler(url="http://localhost:9090/escalate")
    """

    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 5.0

    async def __call__(self, record: TraceRecord, ctx: Dict[str, Any]) -> None:
        payload = {
            "constraint_id": record.constraint_id,
            "point": record.point.value,
            "tool": record.tool,
            "action_id": record.action_id,
            "klass": record.klass.value,
            "response": record.response.value,
            "fired": record.fired,
        }
        if record.extra:
            ec = record.extra.get("execution_context")
            if ec:
                payload["execution_context"] = ec
        predicate_ctx = {k: v for k, v in ctx.items() if k != "execution_context"}
        if predicate_ctx:
            payload["predicate_context"] = _safe_serialise(predicate_ctx)

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", **self.headers},
        )

        timeout = self.timeout

        def _send() -> int:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status

        try:
            import asyncio
            status = await asyncio.to_thread(_send)
            if status >= 400:
                logger.warning(
                    "WebhookEscalationHandler: endpoint returned HTTP %s for "
                    "constraint=%s action=%s",
                    status,
                    record.constraint_id,
                    record.action_id,
                )
        except urllib.error.URLError as exc:
            logger.warning(
                "WebhookEscalationHandler: delivery failed for constraint=%s "
                "action=%s — %s",
                record.constraint_id,
                record.action_id,
                exc,
            )
        except Exception:
            logger.exception(
                "WebhookEscalationHandler: unexpected error for constraint=%s action=%s",
                record.constraint_id,
                record.action_id,
            )


def _safe_serialise(obj: Any) -> Any:
    """Best-effort JSON-safe conversion; non-serialisable values become str."""
    if isinstance(obj, dict):
        return {k: _safe_serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialise(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


__all__ = ["WebhookEscalationHandler"]
