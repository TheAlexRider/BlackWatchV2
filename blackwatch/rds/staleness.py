"""Long-idle RDS session detection.

Called every scheduler tick. Finds RDS sessions in `rds_active_sessions`
that have been open longer than IDLE_THRESHOLD_HOURS without a matching
disconnection event -- these are usually:
  * a leaked / stolen credential someone is holding open,
  * a `psql` window a developer forgot they were in,
  * a broken app connection pool that never returns members.

We emit `rds.session.long_idle` per stale session. Deterministic event_id
per (session_id, day) means the same session only fires once per day, even
though we check every tick. That's the notification dedup path we already
trust for host-staleness."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from .. import pipeline, storage
from ..event import Actor, Category, Event, Outcome, Source, Target, Transport

IDLE_THRESHOLD_HOURS = 24


def check() -> None:
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=IDLE_THRESHOLD_HOURS)
    try:
        sessions = storage.list_rds_active_sessions(limit=1000)
    except Exception:
        return
    for s in sessions:
        connected = s.get("connected_at")
        if not connected or connected >= threshold:
            continue
        session_id = s["session_id"]
        # One event per session per day; the same open session tomorrow will
        # emit again -- prompts action but doesn't spam within a day.
        day = now.strftime("%Y%m%d")
        event_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"rds.session.long_idle::{session_id}::{day}",
        ))
        idle_hours = int((now - connected).total_seconds() / 3600)
        try:
            pipeline.process_event(Event(
                event_id=event_id,
                source=Source(module="aws.rds", transport=Transport.poll),
                event_time=now,
                category=Category.other,
                action="rds.session.long_idle",
                outcome=Outcome.failure,
                actor=Actor(
                    principal=s.get("db_user"),
                    source_ip=s.get("source_ip"),
                ),
                target=Target(
                    id=s["db_instance"], type="rds.db",
                    name=s["db_instance"],
                ),
                extra={
                    "db_instance": s["db_instance"],
                    "user": s.get("db_user"),
                    "database": s.get("db_name"),
                    "source_ip": s.get("source_ip"),
                    "session_id": session_id,
                    "idle_hours": idle_hours,
                    "connected_at": connected.isoformat(),
                    "tags": {
                        "env": "prod",
                        "db_instance": s["db_instance"],
                    },
                    "message": (
                        f"{s['db_instance']}: session for "
                        f"{s.get('db_user') or 'unknown'} has been idle for "
                        f"{idle_hours}h "
                        f"(source: {s.get('source_ip') or 'unknown'})"
                    ),
                },
                raw={"derived": "rds_staleness", "session_id": session_id},
            ))
        except Exception:
            pass
