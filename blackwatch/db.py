"""Postgres connection pool + migration runner.

Migrations run at most ONCE per file. Every migration must be idempotent at
the DDL level (CREATE TABLE IF NOT EXISTS, ALTER TABLE ... ADD COLUMN IF NOT
EXISTS) and guarded at the DML level (INSERT ... ON CONFLICT DO NOTHING,
UPDATE ... WHERE <sentinel>). Destructive SQL is rejected before execution by
the data-safety guard.
"""

from __future__ import annotations

from pathlib import Path

from psycopg_pool import ConnectionPool

from .config import settings
from .db_safety import assert_migration_safe

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
    """Run every SQL file in sorted order that hasn't been applied yet.

    On the FIRST run against a database that already went through the old
    replay-every-time runner: schema_migrations is empty, so every existing
    migration is applied again. That's safe because every migration is written
    to be idempotent (see module docstring). This is a one-time cost; from
    the second run onward, the tracker skips everything and only new
    migrations run.

    DO NOT try to be clever and pre-mark old migrations as applied based on
    "does the events table exist" — that hides the case where the deploy
    also brought a BRAND NEW migration file that hasn't run yet.
    """
    assert _pool is not None
    with _pool.connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row[0]
            for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()
        }

        for sql_file in sorted(_SQL_DIR.glob("*.sql")):
            if sql_file.name in applied:
                continue
            sql = sql_file.read_text(encoding="utf-8")
            assert_migration_safe(sql, source=sql_file.name)
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s) "
                "ON CONFLICT (filename) DO NOTHING",
                (sql_file.name,),
            )
