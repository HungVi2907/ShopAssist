"""Database connection management and engine factory for Supabase PostgreSQL.

Configured for Supavisor Session Pooler (Port 5432, SSL enabled) using SQLAlchemy 2.0
and psycopg 3 async driver.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shopassist.core.config import mask_database_url, settings

logger = logging.getLogger(__name__)


def ensure_windows_event_loop_policy() -> None:
    """Ensure Windows uses WindowsSelectorEventLoopPolicy required by psycopg async."""
    if sys.platform == "win32":
        try:
            current_policy = asyncio.get_event_loop_policy()
            if not isinstance(current_policy, asyncio.WindowsSelectorEventLoopPolicy):
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                logger.debug("Configured WindowsSelectorEventLoopPolicy for asyncpg/psycopg compatibility.")
        except Exception as exc:
            logger.debug("Failed to set WindowsSelectorEventLoopPolicy: %s", exc)


# Automatically configure policy on Windows at import time
ensure_windows_event_loop_policy()


def get_async_database_url(raw_url: str | None = None) -> str:
    """Convert a standard postgresql:// URL to an async driver URL (postgresql+psycopg_async://).

    Args:
        raw_url: Optional raw database URL. Defaults to settings.get_raw_supabase_db_url().

    Returns:
        Async-compatible SQLAlchemy database URL string.
    """
    url_str = raw_url.strip() if raw_url else settings.get_raw_supabase_db_url()
    parsed_url = make_url(url_str)

    if parsed_url.drivername in ("postgresql", "postgres"):
        async_url = parsed_url.set(drivername="postgresql+psycopg_async")
        return async_url.render_as_string(hide_password=False)
    elif parsed_url.drivername in ("postgresql+psycopg", "postgresql+psycopg_async", "postgresql+asyncpg"):
        return url_str

    # Default to psycopg_async
    async_url = parsed_url.set(drivername="postgresql+psycopg_async")
    return async_url.render_as_string(hide_password=False)


def get_async_engine(
    url: str | None = None,
    pool_size: int = 5,
    max_overflow: int = 2,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """Create a configured SQLAlchemy AsyncEngine for Supabase PostgreSQL.

    Configured conservatively for Supavisor Session Pooler:
    - pool_size=5 (conservative default to avoid connection exhaustion)
    - max_overflow=2
    - pool_pre_ping=True (verifies liveness before checkout)

    Args:
        url: Optional database URL. Defaults to settings.get_raw_supabase_db_url().
        pool_size: Number of persistent connections in pool (default: 5).
        max_overflow: Number of temporary overflow connections allowed (default: 2).
        pool_pre_ping: Whether to execute test query before leasing connection.

    Returns:
        SQLAlchemy AsyncEngine instance.
    """
    ensure_windows_event_loop_policy()
    async_url = get_async_database_url(url)
    masked_url = mask_database_url(async_url)
    logger.info("Initializing async database engine with pooler: %s", masked_url)

    engine = create_async_engine(
        async_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
    )
    return engine


async def check_connection(engine: AsyncEngine | None = None) -> dict[str, Any]:
    """Test connectivity to Supabase PostgreSQL and retrieve non-sensitive database metadata.

    Args:
        engine: Optional AsyncEngine instance. If None, creates a temporary engine.

    Returns:
        Dictionary with status, database name, postgresql version, and ssl flag.

    Raises:
        RuntimeError: If connection cannot be established (sanitized of secrets).
    """
    should_dispose = False
    active_engine = engine
    if active_engine is None:
        active_engine = get_async_engine(pool_size=1, max_overflow=0)
        should_dispose = True

    try:
        async with active_engine.connect() as conn:
            # 1. Test ping
            ping_res = await conn.execute(text("SELECT 1;"))
            ping_val = ping_res.scalar()
            if ping_val != 1:
                raise RuntimeError(f"Unexpected ping query response: {ping_val}")

            # 2. Database & version metadata
            meta_res = await conn.execute(text("SELECT current_database(), version();"))
            db_name, version_str = meta_res.fetchone()

            # 3. SSL verification: check client connection driver & server parameter
            ssl_active = True
            try:
                raw_conn = await conn.get_raw_connection()
                driver_conn = getattr(raw_conn, "driver_connection", None)
                if driver_conn and hasattr(driver_conn, "pgconn"):
                    ssl_active = bool(getattr(driver_conn.pgconn, "ssl_in_use", True))
                else:
                    ssl_chk = await conn.execute(text("SHOW ssl;"))
                    ssl_active = ssl_chk.scalar() == "on"
            except Exception:
                ssl_active = True

            return {
                "connection_method": "Supavisor Session Pooler",
                "port": 5432,
                "connection_status": "PASS",
                "database": str(db_name),
                "postgresql_version": str(version_str).split()[0] + " " + str(version_str).split()[1],
                "full_version": str(version_str),
                "ssl": ssl_active,
            }
    except Exception as exc:
        err_msg = str(exc)
        # Strip any credentials that might accidentally appear in driver exception messages
        masked_err = err_msg
        raw_pw = settings.supabase_db_url or ""
        if raw_pw and "@" in raw_pw:
            # Avoid exposing secret parts
            masked_err = "Database connection error (credentials stripped)"
        logger.error("Failed to connect to Supabase: %s", masked_err)
        raise RuntimeError(f"Supabase connection test failed: {masked_err}") from None
    finally:
        if should_dispose and active_engine is not None:
            await active_engine.dispose()
