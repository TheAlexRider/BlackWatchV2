"""Absence detection for per-VPC probe agents. If an agent stops reporting,
the entire VPC's http/tcp monitoring is offline — that's worth a high-severity
alert in its own right. Called periodically by the connector scheduler."""

from __future__ import annotations

from datetime import datetime, timezone

from .. import pipeline, storage
from ..event import Category, Event, Outcome, Severity, Source, Target, Transport

STALE_AFTER_SECONDS = 180


def _stale_message(vpc: str, age_seconds: int, last_report) -> str:
    """Match the multi-line style used by services/projection.py so a single
    channel template renders every ECS event consistently."""
    age_min = max(1, age_seconds // 60)
    from datetime import timezone as _tz
    last_str = "—"
    try:
        last_str = last_report.astimezone(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass
    return (
        f"*Probe agent went silent in `{vpc}`*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *VPC:* {vpc}\n"
        f"• *Silent for:* {age_min} min\n"
        f"• *Last report:* {last_str}\n"
        "• *Impact:* HTTP/TCP monitoring for this VPC is offline"
    )


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
            # Whole VPC's probe visibility is offline — critical. Aligns with
            # services/projection._ecs_severity so operators get a consistent
            # severity contract across ecs.probe events.
            severity=Severity.critical,
            target=Target(id=vpc, type="probe.agent", name=f"probe-{vpc}"),
            extra={
                "vpc": vpc,
                "last_report": updated.isoformat(),
                "age_seconds": int(age),
                "message": _stale_message(vpc, int(age), updated),
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
