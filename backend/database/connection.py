"""
Async PostgreSQL connection pool via SQLAlchemy 2.0 + asyncpg.

All database I/O in the application goes through the session factory
returned by get_db().  The engine is created once at import time and
reused for the lifetime of the process.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings

logger = logging.getLogger(__name__)

# NullPool is appropriate for serverless / Railway deployments where the
# process may be recycled frequently.  Switch to AsyncAdaptedQueuePool
# (the default) for long-running servers with many concurrent requests.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a scoped async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context-manager version for use outside FastAPI dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Create all tables that don't already exist.

    Called once during application startup.  In production you should
    run Alembic migrations instead, but this is kept as a convenience
    for initial setup and CI environments.
    """
    from database.models import Base  # local import avoids circular imports

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified / created successfully.")
    except Exception as exc:
        logger.error("Failed to initialise database: %s", exc)
        raise
