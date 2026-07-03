"""RDS session projection.

Consumes events from the aws.rds adapter and maintains rds_active_sessions.

  * rds.session.start -> INSERT (or refresh last_seen_at if we've seen the
    session_id before). Emits nothing derived -- the start IS the signal.
  * rds.session.end   -> mark disconnected, record duration.
    Emits nothing -- the end IS the signal.

This is pure state-tracking; alerting on unusual sessions (new IP for a user,
concurrent sessions, out-of-hours, etc.) lives in the rule layer. Keeping the
projection dumb means adding new detections doesn't touch state code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Event

_MODULE = "aws.rds"


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    action = event.action
    e = event.extra or {}
    session_id = e.get("session_id")
    if not session_id:
        return []
    ts = event.event_time or datetime.now(timezone.utc)

    if action == "rds.session.start":
        try:
            storage.upsert_rds_session_start(
                session_id,
                db_instance=e.get("db_instance") or "unknown",
                source_type=e.get("source_type") or "postgres",
                db_user=e.get("user"),
                db_name=e.get("database"),
                source_ip=e.get("source_ip"),
                source_port=e.get("source_port"),
                connected_at=ts,
                extra={"backend_pid": e.get("backend_pid")},
            )
        except Exception:
            pass
        return []

    if action == "rds.session.end":
        try:
            storage.close_rds_session(
                session_id,
                disconnected_at=ts,
                duration_seconds=e.get("duration_seconds"),
            )
        except Exception:
            pass
        return []

    return []
