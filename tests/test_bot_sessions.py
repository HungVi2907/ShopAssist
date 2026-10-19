"""Unit tests for BotSessionManager and concurrency locks (Phase 16)."""

from __future__ import annotations

import asyncio
import time
from shopassist.bot.session import BotSessionManager


def test_session_manager_stable_session_id():
    manager = BotSessionManager()
    sess1 = manager.get_session_id(1001)
    sess2 = manager.get_session_id(1001)
    assert sess1 == sess2
    assert sess1.startswith("tg_1001_")


def test_session_manager_session_isolation():
    manager = BotSessionManager()
    sess_a = manager.get_session_id(1001)
    sess_b = manager.get_session_id(1002)
    assert sess_a != sess_b
    assert "1001" in sess_a
    assert "1002" in sess_b


def test_session_manager_reset_session():
    manager = BotSessionManager()
    sess_before = manager.get_session_id(1001)
    sess_after = manager.reset_session(1001)
    assert sess_before != sess_after
    assert sess_after.startswith("tg_1001_")
    # Subsequent calls should return the new session ID
    assert manager.get_session_id(1001) == sess_after


def test_session_manager_per_chat_locks():
    manager = BotSessionManager()
    lock_a1 = manager.get_lock(1001)
    lock_a2 = manager.get_lock(1001)
    lock_b = manager.get_lock(1002)

    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b


def test_session_manager_concurrency_lock_behavior():
    manager = BotSessionManager()
    lock = manager.get_lock(1001)

    async def run():
        assert not lock.locked()
        async with lock:
            assert lock.locked()
        assert not lock.locked()

    asyncio.run(run())


def test_session_manager_prune_inactive():
    manager = BotSessionManager()
    manager.get_session_id(1001)
    manager.get_session_id(1002)

    # Artificially age chat 1001
    manager._last_active[1001] = time.time() - 1000.0

    pruned = manager.prune_inactive(max_idle_seconds=500.0)
    assert pruned == 1
    assert 1001 not in manager._sessions
    assert 1002 in manager._sessions
