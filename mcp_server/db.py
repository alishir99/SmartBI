"""Database access for the MCP server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None
_coverage: tuple[date, date] | None = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.dsn, min_size=1, max_size=10,
            command_timeout=settings.statement_timeout_ms / 1000,
        )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("connection pool not initialised")
    return _pool


@asynccontextmanager
async def tenant_connection(supplier_id: int) -> AsyncIterator[asyncpg.Connection]:
    """A transaction scoped to one supplier."""
    async with pool().acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.supplier_id', $1, true)", str(int(supplier_id)))
            await connection.execute(
                f"SET LOCAL statement_timeout = {int(settings.statement_timeout_ms)}")
            yield connection


async def coverage() -> tuple[date, date]:
    """First and last date the warehouse covers, cached for the process lifetime."""
    global _coverage
    if _coverage is None:
        async with pool().acquire() as connection:
            row = await connection.fetchrow(
                "SELECT MIN(date) AS from_date, MAX(date) AS to_date FROM dim_date")
        if row is None or row["from_date"] is None:
            raise RuntimeError("no data: run scripts/seed.py")
        _coverage = (row["from_date"], row["to_date"])
    return _coverage
