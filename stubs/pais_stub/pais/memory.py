"""Stub for pais.memory — minimal InMemorySessionStore for SARC integration tests."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class InMemorySessionStore:
    """Minimal stub matching the real pais InMemorySessionStore interface.

    Behaviour matches real PAIS: add_event silently drops events for sessions
    that have not been explicitly created via create(session_id).
    """

    def __init__(self) -> None:
        self._sessions: set[str] = set()
        self._events: List[Dict[str, Any]] = []

    def create(self, session_id: str) -> None:
        self._sessions.add(session_id)

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if session_id not in self._sessions:
            return False  # silent drop — same behaviour as real PAIS
        self._events.append(
            {
                "session_id": session_id,
                "event_type": event_type,
                "content": content,
                "metadata": metadata,
            }
        )
        return True

    def list_events(
        self,
        session_id: str,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            e
            for e in self._events
            if e["session_id"] == session_id
            and (event_type is None or e["event_type"] == event_type)
        ]
