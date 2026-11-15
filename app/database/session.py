"""Async SQLAlchemy engine and session management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs

from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.config import get_settings
from app.database.models import Base

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    global _engine, _session_factory
    settings = get_settings()
    url = settings.database_url
    connect_args = {}

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if url.startswith("postgresql+asyncpg://"):
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        if "sslmode" in query_params:
            ssl_mode = query_params["sslmode"][0]
            if ssl_mode in ("require", "verify-ca", "verify-full"):
                connect_args["ssl"] = ssl_mode
            url = url.split("?")[0]

    _engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_timeout=30.0,
        connect_args=connect_args,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    logger.info("Database engine initialized.")


async def create_all() -> None:
    if _engine is None:
        init_engine()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified.")


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Session rollback: {e}", exc_info=True)
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed.")
    _engine = None
    _session_factory = None
