"""Absence detection for per-VPC probe agents. If an agent stops reporting,
the entire VPC's http/tcp monitoring is offline — that's worth a high-severity
alert in its own right. Called periodically by the connector scheduler."""

from __future__ import annotations

from datetime import datetime, timezone

from .. import pipeline, storage
from ..event import Category, Event, Outcome, Source, Target, Transport

STALE_AFTER_SECONDS = 180


def check() -> None:
    now = datetime.now(timezone.utc)
    try:
        agents = storage.list_probe_agents()
    except Exception:
        return
    for a in agents:
        updated = a.get("last_report")
        if not a.get("active") or updated is None:
            continue
        age = (now - updated).total_seconds()
        if age <= STALE_AFTER_SECONDS:
            continue
        vpc = a["vpc"]
        event = Event(
            source=Source(module="ecs.probe", transport=Transport.poll),
            event_time=now,
            category=Category.other,
            action="probe.agent.stale",
            outcome=Outcome.failure,
            target=Target(id=vpc, type="probe.agent", name=f"probe-{vpc}"),
            extra={
                "vpc": vpc,
                "last_report": updated.isoformat(),
                "age_seconds": int(age),
            },
            raw={"derived": "staleness"},
        )
        try:
            pipeline.process_event(event)
            storage.upsert_probe_agent(
                vpc, last_report=updated,
                agent_version=a.get("agent_version"), active=False,
            )
        except Exception:
            pass
