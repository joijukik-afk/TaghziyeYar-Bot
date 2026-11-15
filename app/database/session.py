"""Async SQLAlchemy engine and session management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database.models import Base

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """Create the global async engine and session factory."""
    global _engine, _session_factory
    settings = get_settings()

    url = settings.database_url

    # 👈 کلید اصلی حل مشکل: غیرفعال کردن هر دو کش asyncpg
    connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }

    # Normalize postgres:// and postgresql:// to asyncpg format
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # مدیریت SSL و حذف پارامترهای اضافی از URL
    if "?" in url:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        if "sslmode" in query_params:
            ssl_mode = query_params["sslmode"][0]
            if ssl_mode in ("require", "verify-ca", "verify-full"):
                connect_args["ssl"] = ssl_mode

        url = url.split("?")[0]

    # 👈 استفاده از NullPool برای جلوگیری از نگهداری اتصالات قدیمی
    _engine = create_async_engine(
        url,
        echo=False,
        future=True,
        poolclass=NullPool,
        connect_args=connect_args,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    logger.info("Database engine initialized with all statement caches disabled.")


async def create_all() -> None:
    """Create all tables if they do not exist (Only for development)."""
    if _engine is None:
        init_engine()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified.")


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session scope."""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Database session rollback due to error: {e}", exc_info=True)
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Graceful shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed.")
    _engine = None
    _session_factory = None
