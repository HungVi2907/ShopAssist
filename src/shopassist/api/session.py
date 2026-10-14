"""In-memory bounded session store preparing for Phase 16 Telegram integration.

Provides lightweight, ephemeral conversation history tracking with TTL expiration.
Does NOT carry unverified assumptions or constraints across turns (maintaining safety).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Sequence


@dataclass
class ChatTurn:
    """Single conversational turn consisting of a user query and assistant response."""

    user_query: str
    assistant_overview: str
    status: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionState:
    """Bounded session state tracking recent turns."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    history: list[ChatTurn] = field(default_factory=list)


class InMemorySessionStore:
    """Thread-safe, TTL-bounded in-memory session manager."""

    def __init__(self, ttl_seconds: int = 3600, max_messages: int = 10) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> SessionState:
        """Retrieve existing active session or create a new session state."""
        async with self._lock:
            now = time.time()
            self._evict_expired_unlocked(now)

            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.last_accessed = now
                return session

            session = SessionState(session_id=session_id, created_at=now, last_accessed=now)
            self._sessions[session_id] = session
            return session

    async def add_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_overview: str,
        status: str,
    ) -> None:
        """Record a completed conversation turn into the session history."""
        async with self._lock:
            now = time.time()
            self._evict_expired_unlocked(now)

            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState(
                    session_id=session_id, created_at=now, last_accessed=now
                )

            session = self._sessions[session_id]
            session.last_accessed = now
            session.history.append(
                ChatTurn(
                    user_query=user_query,
                    assistant_overview=assistant_overview,
                    status=status,
                    timestamp=now,
                )
            )

            # Cap history length to max_messages
            if len(session.history) > self.max_messages:
                session.history = session.history[-self.max_messages :]

    async def get_history(self, session_id: str) -> list[ChatTurn]:
        """Return shallow copy of history turns for a session."""
        async with self._lock:
            now = time.time()
            self._evict_expired_unlocked(now)
            session = self._sessions.get(session_id)
            if not session:
                return []
            session.last_accessed = now
            return list(session.history)

    async def clear_session(self, session_id: str) -> None:
        """Explicitly clear a session."""
        async with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_expired_unlocked(self, current_time: float) -> None:
        """Evict sessions whose last_accessed timestamp exceeds TTL."""
        expired_keys = [
            sid
            for sid, state in self._sessions.items()
            if (current_time - state.last_accessed) > self.ttl_seconds
        ]
        for sid in expired_keys:
            del self._sessions[sid]

    @property
    def active_session_count(self) -> int:
        """Return number of currently stored active sessions."""
        return len(self._sessions)
