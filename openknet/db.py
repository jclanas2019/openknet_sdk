from __future__ import annotations
import datetime
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def _is_pg(url: str) -> bool:
    return "postgresql" in url


def get_engine():
    global _engine
    if _engine is None:
        url = settings.get_db_url()
        if _is_pg(url):
            _engine = create_async_engine(
                url,
                pool_size=settings.pg_pool_size,
                max_overflow=settings.pg_max_overflow,
                pool_timeout=settings.pg_pool_timeout,
                pool_recycle=settings.pg_pool_recycle,
                pool_pre_ping=True,
                echo=settings.pg_echo,
            )
        else:
            _engine = create_async_engine(
                url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
                echo=False,
            )
    return _engine


def current_dialect() -> str:
    return get_engine().dialect.name


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from .models.orm import Base as ModelBase  # noqa
    async with get_engine().begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)
        if current_dialect() == "postgresql":
            await _init_postgres(conn)
        else:
            await _init_sqlite(conn)


async def _init_postgres(conn) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_chunks_fts_gin
        ON chunks USING GIN (to_tsvector('english', text))
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_entity_name_trgm
        ON entities USING GIN (name gin_trgm_ops)
    """))


async def _init_sqlite(conn) -> None:
    await conn.execute(text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
        USING fts5(chunk_id UNINDEXED, project_id UNINDEXED, text, tokenize='porter ascii')
    """))


async def check_db_health() -> dict:
    """Verify DB is reachable and return latency."""
    import time
    t0 = time.monotonic()
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
