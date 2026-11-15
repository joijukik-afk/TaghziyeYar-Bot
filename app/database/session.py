"""Async SQLAlchemy engine and session management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import uuid

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

def _unique_stmt_name() -> str:
    """تولید یک نام یکتا برای هر دستور آماده."""
    return f"__asyncpg_{uuid.uuid4()}__"

def init_engine() -> None:
    """Create the global async engine and session factory."""
    global _engine, _session_factory
    settings = get_settings()

    url = settings.database_url

    # ۱. اصلاح آدرس دیتابیس
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # ۲. پاکسازی کامل آدرس از هرگونه پارامتر اضافی (مثل sslmode)
    if "?" in url:
        url = url.split("?")[0]

    # ۳. تنظیمات اتصال به asyncpg
    connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": _unique_stmt_name,
        "server_settings": {"jit": "off"},
    }

    # ۴. اجبار به استفاده از SSL (چون Neon به آن نیاز دارد)
    if "neon.tech" in url:
        connect_args["ssl"] = "require"

    # ۵. ساخت موتور دیتابیس
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
    logger.info("Database engine initialized successfully with all caches disabled.")


async def create_all() -> None:
    """Create all tables if they do not exist."""
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
