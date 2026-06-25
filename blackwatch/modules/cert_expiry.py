"""Cert expiry adapter — turns TLS probe reports into normalized events.

Consumes payloads from the `cert_probe` connector. Each probe report covers a
set of `targets`; this adapter emits zero or one event per target depending
on its expiry posture.

Emits (action -> rule-assigned severity):
  * cert.expired             — days_remaining < 0
  * cert.expiring.critical   — 0 ≤ days < 7
  * cert.expiring.high       — 7 ≤ days < 14
  * cert.expiring.warning    — 14 ≤ days < 30
  * cert.probe.failed        — couldn't reach / parse the endpoint

Healthy certs (days >= 30) produce **no event** — silence is golden. The
connector's `last_run_at` + result-count tells the operator the scan ran.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..event import Actor, Event, Outcome, Source, Transport
from .base import Adapter, IngestContext


def _action_for(target: dict[str, Any]) -> str | None:
    """Returns the event action for a target, or None if healthy + no event."""
    if not target.get("ok"):
        return "cert.probe.failed"
    days = target.get("days_remaining")
    if days is None:
        return "cert.probe.failed"
    if days < 0:
        return "cert.expired"
    if days < 7:
        return "cert.expiring.critical"
    if days < 14:
        return "cert.expiring.high"
    if days < 30:
        return "cert.expiring.warning"
    return None  # healthy — no event


class CertExpiryAdapter(Adapter):
    module = "cert"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        report = raw if isinstance(raw, dict) else {}
        targets = report.get("targets") or []
        now = datetime.now(timezone.utc)

        events: list[Event] = []
        for t in targets:
            if not isinstance(t, dict):
                continue
            action = _action_for(t)
            if action is None:
                continue

            extra = {
                "host": t.get("host"),
                "port": t.get("port"),
                "subject": t.get("subject"),
                "issuer": t.get("issuer"),
                "not_after": t.get("not_after"),
                "days_remaining": t.get("days_remaining"),
                "sans": t.get("sans") or [],
            }
            if t.get("error"):
                extra["error"] = t["error"]

            target_id = t.get("name") or f"{t.get('host')}:{t.get('port')}"
            event = Event(
                source=Source(
                    module="cert",
                    account=ctx.account,
                    region=ctx.region,
                    transport=Transport.poll,
                ),
                event_time=now,
                category="audit",
                action=action,
                outcome=Outcome.success if t.get("ok") else Outcome.failure,
                actor=Actor(),
                target={
                    "id": target_id,
                    "type": "tls_endpoint",
                    "name": t.get("name") or target_id,
                },
                extra=extra,
                raw=t,
            )
            events.append(event)
        return events
