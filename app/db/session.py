from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# Make database connection optional for Phase 1
if settings.database_url:
    # Supabase pooler (PgBouncer in transaction mode) doesn't support
    # prepared statements — disable asyncpg's statement cache.
    _connect_args = {}
    if "pooler.supabase.com" in (settings.database_url or ""):
        _connect_args["statement_cache_size"] = 0

    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        connect_args=_connect_args,
    )

    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
else:
    engine = None
    async_session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI routes to get a database session."""
    if async_session_factory is None:
        raise RuntimeError("Database is not configured. Set DATABASE_URL environment variable.")

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
