"""Absence detection: if a host's agent stops reporting, raise an alert. Called
periodically by the connector scheduler. Emits host.agent.stale once per
transition (flips active=false), so it doesn't repeat every tick; the next
heartbeat flips active back to true via the projection."""

from __future__ import annotations

from datetime import datetime, timezone

from .. import pipeline, storage
from ..event import Category, Event, Outcome, Source, Target, Transport

STALE_AFTER_SECONDS = 180


def check() -> None:
    now = datetime.now(timezone.utc)
    try:
        rows = storage.list_host_status()
    except Exception:
        return
    for row in rows:
        updated = row.get("updated_at")
        if not row.get("active") or updated is None:
            continue
        age = (now - updated).total_seconds()
        if age <= STALE_AFTER_SECONDS:
            continue
        event = Event(
            source=Source(module="ec2.host", transport=Transport.poll, account=row.get("account"),
                          region=row.get("region")),
            event_time=now,
            category=Category.host,
            action="host.agent.stale",
            outcome=Outcome.failure,
            target=Target(id=row["instance_id"], type="ec2.instance", name=row.get("hostname")),
            extra={
                "instance_id": row["instance_id"],
                "last_seen": updated.isoformat(),
                "age_seconds": int(age),
            },
            raw={"derived": "staleness"},
        )
        try:
            pipeline.process_event(event)
            storage.set_host_active(row["instance_id"], False)
        except Exception:
            pass
