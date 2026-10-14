"""Unit tests for InMemorySessionStore (Phase 15)."""

from __future__ import annotations

import asyncio
import functools
import pytest

from shopassist.api.session import InMemorySessionStore


def async_test(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


@async_test
async def test_session_creation_and_turn_addition():
    store = InMemorySessionStore(ttl_seconds=10, max_messages=5)
    session_id = "test-session-1"

    session = await store.get_or_create(session_id)
    assert session.session_id == session_id
    assert len(session.history) == 0

    await store.add_turn(
        session_id=session_id,
        user_query="Puma running shoes under 3000",
        assistant_overview="Found 3 great Puma running shoes.",
        status="SUCCESS",
    )

    history = await store.get_history(session_id)
    assert len(history) == 1
    assert history[0].user_query == "Puma running shoes under 3000"
    assert history[0].status == "SUCCESS"


@async_test
async def test_session_history_bounding():
    max_msgs = 3
    store = InMemorySessionStore(ttl_seconds=60, max_messages=max_msgs)
    session_id = "bounded-session"

    for i in range(5):
        await store.add_turn(
            session_id=session_id,
            user_query=f"query {i}",
            assistant_overview=f"overview {i}",
            status="SUCCESS",
        )

    history = await store.get_history(session_id)
    assert len(history) == max_msgs
    # Oldest turns should have been evicted
    assert history[0].user_query == "query 2"
    assert history[-1].user_query == "query 4"


@async_test
async def test_session_ttl_eviction():
    # 1 second TTL
    store = InMemorySessionStore(ttl_seconds=1, max_messages=5)
    session_id = "ephemeral-session"

    await store.add_turn(
        session_id=session_id,
        user_query="shoes",
        assistant_overview="overview",
        status="SUCCESS",
    )

    assert store.active_session_count == 1
    await asyncio.sleep(1.1)

    # Accessing another or checking active count after sleep should trigger eviction
    history = await store.get_history(session_id)
    assert len(history) == 0
    assert store.active_session_count == 0


@async_test
async def test_session_clear():
    store = InMemorySessionStore(ttl_seconds=60, max_messages=5)
    session_id = "to-be-cleared"

    await store.add_turn(session_id, "query", "overview", "SUCCESS")
    assert store.active_session_count == 1

    await store.clear_session(session_id)
    assert store.active_session_count == 0
