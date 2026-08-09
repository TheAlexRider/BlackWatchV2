"""SQLite store for threat-intel feeds. Kept OUT of the events database on
purpose: refreshes rewrite whole feeds and we don't want that contention on
the hot events postgres."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_LOCK = threading.Lock()


def data_dir() -> Path:
    root = Path(os.environ.get("BLACKWATCH_DATA_DIR", ".")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def intel_db_path() -> Path:
    return data_dir() / "intel.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ti_ip4 (
    net_start INTEGER NOT NULL,
    net_end   INTEGER NOT NULL,
    feed      TEXT NOT NULL,
    tags      TEXT,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ti_ip4_range ON ti_ip4(net_start, net_end);
CREATE INDEX IF NOT EXISTS ix_ti_ip4_feed  ON ti_ip4(feed);

CREATE TABLE IF NOT EXISTS ti_feed_meta (
    feed         TEXT PRIMARY KEY,
    url          TEXT,
    last_success INTEGER,
    last_status  TEXT,
    entries      INTEGER
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(intel_db_path(), timeout=15, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init() -> None:
    with _LOCK:
        conn = connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()


def replace_feed(feed: str, url: str, rows: list[tuple[int, int, str]]) -> int:
    """Atomically replace all rows for one feed. rows: (net_start, net_end, tags)."""
    import time

    init()
    now = int(time.time())
    with _LOCK:
        conn = connect()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM ti_ip4 WHERE feed = ?", (feed,))
            conn.executemany(
                "INSERT INTO ti_ip4(net_start, net_end, feed, tags, updated_at) VALUES (?,?,?,?,?)",
                [(s, e, feed, t, now) for (s, e, t) in rows],
            )
            conn.execute(
                "INSERT INTO ti_feed_meta(feed,url,last_success,last_status,entries) VALUES(?,?,?,?,?)"
                " ON CONFLICT(feed) DO UPDATE SET url=excluded.url,last_success=excluded.last_success,"
                " last_status=excluded.last_status, entries=excluded.entries",
                (feed, url, now, "ok", len(rows)),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return len(rows)


def record_failure(feed: str, url: str, status: str) -> None:
    init()
    with _LOCK:
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO ti_feed_meta(feed,url,last_success,last_status,entries) VALUES(?,?,NULL,?,0)"
                " ON CONFLICT(feed) DO UPDATE SET url=excluded.url, last_status=excluded.last_status",
                (feed, url, status),
            )
        finally:
            conn.close()


def feed_meta() -> list[dict]:
    init()
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT feed,url,last_success,last_status,entries FROM ti_feed_meta ORDER BY feed"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "feed": r[0],
            "url": r[1],
            "last_success": r[2],
            "last_status": r[3],
            "entries": r[4],
        }
        for r in rows
    ]


def lookup_ip4(ip_int: int) -> list[tuple[str, str | None]]:
    """Return list of (feed, tags) matching this ip. Small result set."""
    conn = connect()
    try:
        return list(
            conn.execute(
                "SELECT feed, tags FROM ti_ip4 WHERE net_start <= ? AND net_end >= ?",
                (ip_int, ip_int),
            )
        )
    finally:
        conn.close()
