"""Tests for handlers.py — WebhookEscalationHandler and _safe_serialise."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

import pytest

from sarc_governance import (
    Constraint,
    ConstraintSpec,
    EscalationRouter,
    GovernanceToolset,
    WebhookEscalationHandler,
)
from sarc_governance.constraints import ConstraintClass, EnforcementPoint, Response
from sarc_governance.handlers import _safe_serialise
from sarc_governance.trace import TraceRecord

from tests.conftest import StubToolset, escalation_pag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(**kwargs) -> TraceRecord:
    defaults = dict(
        action_id="act-1",
        tool="test_tool",
        point=EnforcementPoint.PAG,
        constraint_id="c1",
        klass=ConstraintClass.HARD,
        fired=True,
        response=Response.BLOCK_OR_ESCALATE,
    )
    defaults.update(kwargs)
    return TraceRecord(**defaults)


class _CapturingServer:
    """Minimal HTTP server that captures the first POST body."""

    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.received.append(json.loads(body))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass  # silence

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return port

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


# ===========================================================================
# WebhookEscalationHandler — delivery
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_posts_json_payload():
    srv = _CapturingServer()
    port = srv.start()
    try:
        handler = WebhookEscalationHandler(url=f"http://127.0.0.1:{port}/escalate")
        rec = _make_record()
        await handler(rec, {"tool": "test_tool", "args": {"x": 1}})

        assert len(srv.received) == 1
        payload = srv.received[0]
        assert payload["constraint_id"] == "c1"
        assert payload["point"] == "PAG"
        assert payload["tool"] == "test_tool"
        assert payload["fired"] is True
        assert payload["predicate_context"]["args"] == {"x": 1}
    finally:
        srv.stop()


@pytest.mark.asyncio
async def test_webhook_includes_execution_context_from_extra():
    srv = _CapturingServer()
    port = srv.start()
    try:
        handler = WebhookEscalationHandler(url=f"http://127.0.0.1:{port}/escalate")
        rec = _make_record(extra={"execution_context": {"agent_id": "agent-a", "tenant_id": "t1"}})
        await handler(rec, {})

        payload = srv.received[0]
        assert payload["execution_context"]["agent_id"] == "agent-a"
    finally:
        srv.stop()


@pytest.mark.asyncio
async def test_webhook_sends_custom_headers():
    received_headers: List[Dict[str, str]] = []

    class _HeaderCapture(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            received_headers.append(dict(self.headers))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    from http.server import HTTPServer as _HTTP
    server = _HTTP(("127.0.0.1", 0), _HeaderCapture)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        handler = WebhookEscalationHandler(
            url=f"http://127.0.0.1:{port}/escalate",
            headers={"X-Api-Key": "secret"},
        )
        await handler(_make_record(), {})
        hdrs = {k.lower(): v for k, v in received_headers[0].items()}
        assert hdrs.get("x-api-key") == "secret"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_webhook_swallows_connection_error():
    """A dead endpoint must not raise — the agent loop must continue."""
    handler = WebhookEscalationHandler(url="http://127.0.0.1:1/unreachable", timeout=0.5)
    # Should complete without raising
    await handler(_make_record(), {})


@pytest.mark.asyncio
async def test_webhook_logs_http_error_status(caplog):
    """A 4xx response from the endpoint should log a warning, not raise."""

    class _ErrorHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(422)
            self.end_headers()

        def log_message(self, *args):
            pass

    from http.server import HTTPServer as _HTTP
    server = _HTTP(("127.0.0.1", 0), _ErrorHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        handler = WebhookEscalationHandler(url=f"http://127.0.0.1:{port}/escalate")
        import logging
        with caplog.at_level(logging.WARNING, logger="sarc_governance.handlers"):
            await handler(_make_record(), {})
        assert "422" in caplog.text
    finally:
        server.shutdown()


# ===========================================================================
# WebhookEscalationHandler — integration with GovernanceToolset
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_called_on_escalation_via_governance():
    srv = _CapturingServer()
    port = srv.start()
    try:
        handler = WebhookEscalationHandler(url=f"http://127.0.0.1:{port}/escalate")
        spec = ConstraintSpec(constraints=[escalation_pag(lambda _: True)])
        toolset = GovernanceToolset(
            wrapped=StubToolset(),
            spec=spec,
            router=EscalationRouter(handler=handler),
        )
        await toolset.call_tool("tool", {})
        assert len(srv.received) == 1
        assert srv.received[0]["constraint_id"] == "ce_test"
    finally:
        srv.stop()


# ===========================================================================
# _safe_serialise
# ===========================================================================


def test_safe_serialise_passthrough_primitives():
    assert _safe_serialise({"a": 1, "b": "x", "c": True}) == {"a": 1, "b": "x", "c": True}


def test_safe_serialise_converts_non_serialisable():
    class Weird:
        def __repr__(self):
            return "Weird()"

    result = _safe_serialise({"obj": Weird()})
    assert result["obj"] == "Weird()"


def test_safe_serialise_nested():
    result = _safe_serialise({"args": {"amount": 500, "obj": object()}})
    assert result["args"]["amount"] == 500
    assert isinstance(result["args"]["obj"], str)


# ===========================================================================
# _action_seq lock — parallel calls produce unique monotonic IDs
# ===========================================================================


@pytest.mark.asyncio
async def test_parallel_calls_produce_unique_action_ids():
    """Concurrent call_tool invocations must not share an action_id."""
    inner = StubToolset()
    spec = ConstraintSpec()
    governed = GovernanceToolset(wrapped=inner, spec=spec)

    n = 50
    await asyncio.gather(*[governed.call_tool("t", {}) for _ in range(n)])

    # Inner toolset records one call per invocation
    assert len(inner.calls) == n
    # action_seq should have incremented to n
    assert governed._action_seq == n


@pytest.mark.asyncio
async def test_action_ids_are_monotonically_increasing():
    """Action IDs must be strictly increasing under concurrent load."""
    class RecordingToolset:
        async def call_tool(self, name, args, ctx, tool):
            return {}

    spec = ConstraintSpec(
        constraints=[
            Constraint(
                id="capture",
                klass="hard",
                verif="PAG",
                response="block",
                predicate=lambda ctx: False,  # never fires, just lets us see trace
            )
        ]
    )

    governed = GovernanceToolset(wrapped=RecordingToolset(), spec=spec)
    await asyncio.gather(*[governed.call_tool("t", {}) for _ in range(20)])
    assert governed._action_seq == 20
