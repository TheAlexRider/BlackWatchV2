"""Postgres connection pool + migration runner.

Migrations run at most ONCE per file. On first startup against a database that
already contains BW schema (from before this tracker existed), every existing
migration is backfilled into `schema_migrations` as applied — otherwise we'd
re-run legacy files (including anything with non-idempotent DML) on upgrade.
"""

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


def _existing_events_table(conn) -> bool:
    """True if the events table already exists — signal that this DB was
    populated before the versioned migration runner landed."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'events' LIMIT 1"
    ).fetchone()
    return row is not None


def _run_migrations() -> None:
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

        all_migrations = sorted(_SQL_DIR.glob("*.sql"))

        # First run against a DB that already has BW schema — backfill so we
        # don't re-execute legacy migrations (some contain non-idempotent DML
        # like TRUNCATE that would silently wipe operational state).
        if not applied and _existing_events_table(conn):
            for sql_file in all_migrations:
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s) "
                    "ON CONFLICT (filename) DO NOTHING",
                    (sql_file.name,),
                )
            return

        for sql_file in all_migrations:
            if sql_file.name in applied:
                continue
            conn.execute(sql_file.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s) "
                "ON CONFLICT (filename) DO NOTHING",
                (sql_file.name,),
            )
