"""Postgres connection pool + migration runner."""

from __future__ import annotations

from pathlib import Path

from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None
_SQL_DIR = Path(__file__).parent / "sql"


def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    _pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": True},
    )
    _pool.wait()
    _run_migrations()


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() first")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _run_migrations() -> None:
    assert _pool is not None
    with _pool.connection() as conn:
        for sql_file in sorted(_SQL_DIR.glob("*.sql")):
            conn.execute(sql_file.read_text(encoding="utf-8"))
