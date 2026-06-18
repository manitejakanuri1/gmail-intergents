"""Async Postgres connection pool (Supabase) shared across the app."""
from __future__ import annotations

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Lazily create and return the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            statement_cache_size=0,  # required for the Supabase transaction pooler
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def to_vector_literal(embedding: list[float]) -> str:
    """Format a python list as a pgvector literal: [0.1,0.2,...]."""
    return "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
