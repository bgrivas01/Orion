"""asyncpg connection pool.

The API stays usable without a database (fixtures + live ORS still work), so
`pool()` returns None rather than raising when DATABASE_URL is unset. Callers
must handle that, which also keeps the frontends unblocked before TigerData is
provisioned.
"""

import logging
from pathlib import Path

import asyncpg

from .config import get_settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def connect() -> asyncpg.Pool | None:
    global _pool
    settings = get_settings()
    if not settings.database_url:
        log.warning("DATABASE_URL is not set — running without a database")
        return None
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
        log.info("connected to database")
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool | None:
    return _pool


async def apply_schema(sql_dir: str = "sql") -> None:
    """Idempotently apply the schema. Safe to call on every boot.

    001 is a plain DDL file and runs as one batch. 002 creates a continuous
    aggregate, which TimescaleDB refuses to do inside a transaction block, so
    those statements are sent one at a time.
    """
    p = pool()
    if p is None:
        return

    base = Path(sql_dir)
    async with p.acquire() as conn:
        await conn.execute((base / "001_init.sql").read_text())

        for statement in _split_statements((base / "002_caggs.sql").read_text()):
            try:
                await conn.execute(statement)
            except Exception as exc:  # noqa: BLE001 - continuous aggregates are optional
                log.warning("skipping continuous-aggregate statement: %s", exc)

    log.info("schema applied")


def _split_statements(sql: str) -> list[str]:
    """Split a SQL file into statements, dropping comment-only fragments."""
    out = []
    for chunk in sql.split(";"):
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            out.append(statement)
    return out
