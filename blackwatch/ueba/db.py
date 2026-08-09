"""SQLite state for UEBA baselines. Separate file (baseline.db) so it can be
wiped / backed up independently of the main events store."""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Iterable

_DB_PATH = os.environ.get("BW_UEBA_DB", "baseline.db")
_lock = threading.Lock()
_initialized = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS principal_baseline (
    principal_type TEXT NOT NULL,
    principal_id   TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    value          TEXT NOT NULL,
    first_seen     INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL,
    count          INTEGER NOT NULL,
    PRIMARY KEY (principal_type, principal_id, dimension, value)
);
CREATE INDEX IF NOT EXISTS idx_pb_principal
    ON principal_baseline (principal_type, principal_id);

CREATE TABLE IF NOT EXISTS principal_first_seen (
    principal_type TEXT NOT NULL,
    principal_id   TEXT NOT NULL,
    first_ever     INTEGER NOT NULL,
    PRIMARY KEY (principal_type, principal_id)
);
CREATE INDEX IF NOT EXISTS idx_pfs_principal
    ON principal_first_seen (principal_type, principal_id);
"""


def set_db_path(path: str) -> None:
    """Test hook: override the sqlite file path and force re-init."""
    global _DB_PATH, _initialized
    _DB_PATH = path
    _initialized = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _init_if_needed() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()
        _initialized = True


def get_or_create_first_seen(ptype: str, pid: str, now_ts: int) -> int:
    """Return the principal's first_ever ts, inserting `now_ts` on first sight."""
    _init_if_needed()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO principal_first_seen "
            "(principal_type, principal_id, first_ever) VALUES (?, ?, ?)",
            (ptype, pid, now_ts),
        )
        row = conn.execute(
            "SELECT first_ever FROM principal_first_seen "
            "WHERE principal_type=? AND principal_id=?",
            (ptype, pid),
        ).fetchone()
        return int(row["first_ever"]) if row else now_ts
    finally:
        conn.close()


def upsert_baseline(
    ptype: str, pid: str, dimension: str, value: str, now_ts: int,
) -> int:
    """Upsert a (principal, dimension, value) row. Returns the resulting count.
    A returned count of 1 means this call inserted the row for the first time."""
    _init_if_needed()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO principal_baseline "
            "(principal_type, principal_id, dimension, value, "
            " first_seen, last_seen, count) "
            "VALUES (?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(principal_type, principal_id, dimension, value) "
            "DO UPDATE SET count=count+1, last_seen=excluded.last_seen",
            (ptype, pid, dimension, value, now_ts, now_ts),
        )
        row = conn.execute(
            "SELECT count FROM principal_baseline "
            "WHERE principal_type=? AND principal_id=? "
            "  AND dimension=? AND value=?",
            (ptype, pid, dimension, value),
        ).fetchone()
        return int(row["count"]) if row else 0
    finally:
        conn.close()


def query_baselines(
    principal_type: str | None = None,
    principal_id: str | None = None,
    dimension: str | None = None,
    limit: int = 500,
) -> list[dict]:
    _init_if_needed()
    where: list[str] = []
    args: list = []
    if principal_type:
        where.append("principal_type=?"); args.append(principal_type)
    if principal_id:
        where.append("principal_id=?"); args.append(principal_id)
    if dimension:
        where.append("dimension=?"); args.append(dimension)
    sql = "SELECT * FROM principal_baseline"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY last_seen DESC LIMIT ?"
    args.append(int(limit))
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
    finally:
        conn.close()


def clear_principal(ptype: str, pid: str, dimensions: Iterable[str] | None = None) -> int:
    """Wipe baseline rows for a principal (optionally scoped to dimensions).
    Also resets first_seen so warm-up restarts. Returns rows deleted."""
    _init_if_needed()
    conn = _connect()
    try:
        if dimensions:
            dims = list(dimensions)
            q = "DELETE FROM principal_baseline WHERE principal_type=? AND principal_id=? " \
                "AND dimension IN (" + ",".join("?" * len(dims)) + ")"
            cur = conn.execute(q, (ptype, pid, *dims))
        else:
            cur = conn.execute(
                "DELETE FROM principal_baseline WHERE principal_type=? AND principal_id=?",
                (ptype, pid),
            )
            conn.execute(
                "DELETE FROM principal_first_seen WHERE principal_type=? AND principal_id=?",
                (ptype, pid),
            )
        return int(cur.rowcount or 0)
    finally:
        conn.close()
