"""Async SQLAlchemy engine and session management."""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

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
    """تولید نام یکتا برای هر کوئری جهت جلوگیری از تداخل در Neon"""
    return f"__asyncpg_{uuid.uuid4()}__"

def init_engine() -> None:
    """Create the global async engine and session factory."""
    global _engine, _session_factory
    settings = get_settings()

    url = settings.database_url

    # اصلاح پیشوند اتصال
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # پاکسازی URL و غیرفعال کردن کش در لایه SQLAlchemy
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    clean_query = {k: v for k, v in query_params.items() if k != "prepared_statement_cache_size"}
    clean_query["prepared_statement_cache_size"] = ["0"]
    new_query = urlencode(clean_query, doseq=True)
    url = urlunparse(parsed._replace(query=new_query))

    # تنظیمات asyncpg (غیرفعال کردن کش و نام‌گذاری یکتا)
    connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": _unique_stmt_name,
        "server_settings": {"jit": "off"},
    }

    # اجبار SSL برای Neon
    if "neon.tech" in url:
        connect_args["ssl"] = "require"

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
    logger.info("Database engine initialized with ALL statement caches disabled.")


async def create_all() -> None:
    if _engine is None:
        init_engine()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified.")


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
        logger.error(f"Database session rollback due to error: {e}", exc_info=True)
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
