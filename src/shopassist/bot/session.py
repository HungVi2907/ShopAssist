"""Session resolution and user concurrency management for Telegram Bot (Phase 16)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)


class BotSessionManager:
    """Manages chat-level session continuity, session rotation, and per-user concurrency locks."""

    def __init__(self) -> None:
        self._sessions: dict[int, str] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_active: dict[int, float] = {}

    def get_session_id(self, chat_id: int) -> str:
        """Resolve current session ID for a chat, generating a stable UUID token if new."""
        self._last_active[chat_id] = time.time()
        if chat_id not in self._sessions:
            nonce = uuid.uuid4().hex[:8]
            self._sessions[chat_id] = f"tg_{chat_id}_{nonce}"
            logger.debug("Initialized new session %s for chat %d", self._sessions[chat_id], chat_id)
        return self._sessions[chat_id]

    def reset_session(self, chat_id: int) -> str:
        """Rotate session identifier for a chat, providing a clean conversation context."""
        nonce = uuid.uuid4().hex[:8]
        new_session_id = f"tg_{chat_id}_{nonce}"
        old_session_id = self._sessions.get(chat_id)
        self._sessions[chat_id] = new_session_id
        self._last_active[chat_id] = time.time()
        logger.info(
            "Rotated session for chat %d: %s -> %s",
            chat_id,
            old_session_id,
            new_session_id,
        )
        return new_session_id

    def get_lock(self, chat_id: int) -> asyncio.Lock:
        """Retrieve or create an asyncio.Lock for the specified chat to prevent race conditions."""
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    def prune_inactive(self, max_idle_seconds: float = 86400.0) -> int:
        """Prune session state for chats that have been idle longer than max_idle_seconds."""
        now = time.time()
        expired = [
            cid for cid, last_seen in self._last_active.items()
            if now - last_seen > max_idle_seconds
        ]
        for cid in expired:
            self._sessions.pop(cid, None)
            self._locks.pop(cid, None)
            self._last_active.pop(cid, None)
        return len(expired)
