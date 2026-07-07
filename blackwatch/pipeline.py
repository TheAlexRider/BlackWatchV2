"""Shared ingest pipeline: normalize -> score -> store -> notify -> project.

Both the HTTP /ingest endpoint and the in-app Connectors subsystem call
`ingest_payload`, so there is exactly one path a payload travels regardless of
how it arrived. The event core stays a pure sink — this function is the seam."""

from __future__ import annotations

from typing import Any

from . import correlation, noise, storage
from .event import Event
from .hosts import projection as host_projection
from .modules import registry
from .modules.base import IngestContext
from .notify import router as notify_router
from .posture import projection as posture_projection
from .rds import projection as rds_projection
from .rules import engine as rule_engine
from .s3 import projection as s3_projection
from .services import projection as service_projection
from .vpn import projection as vpn_projection

# Stateful projections run after each event; each ignores events it doesn't own.
# correlation.observe watches for brute-force patterns (host SSH + VPN auth) and
# emits one bruteforce event per IP per window.
_PROJECTIONS = [
    vpn_projection.project,
    host_projection.project,
    service_projection.project,
    s3_projection.project,
    posture_projection.project,
    rds_projection.project,
    correlation.observe,
]

# Routine "still alive" / "still the same" telemetry: drives the projection but
# never gets stored or notified. The projection emits transition / diff events
# (e.g. host.agent.stale, vpn.service.down, host.port.opened, service.down)
# and THOSE are stored. Result: ~99% reduction in event volume, only signal kept.
_PROJECTION_ONLY_ACTIONS = {
    "vpn.service.health",
    "vpn.status.snapshot",
    "vpn.cert.snapshot",
    "host.service.health",
    "host.state.snapshot",
    # FIM coverage rides on every heartbeat (60/min/host) — feed it to the
    # projection (updates fim_coverage table) but DON'T store as an event.
    # Real FIM changes (host.fim.modified/created/deleted/etc.) ARE stored.
    "host.fim.coverage",
    "probe.agent.heartbeat",
    "service.probe.result",
    "s3.bucket.snapshot",
    "s3.scan.completed",
    "aws.posture.finding",
    "aws.posture.scan.completed",
    # RDS Proxy client connects/disconnects fire ~1000/hour on a busy DB —
    # they feed the rds_proxy_sources projection (which fires the once-per-
    # new-IP rds.proxy.source.new event) but we don't want them cluttering
    # the events table or notification pipeline.
    "rds.proxy.client.connect",
    "rds.proxy.client.disconnect",
}


class NormalizationError(Exception):
    """Raised when an adapter cannot parse a payload (maps to HTTP 422)."""


def _process(event: Event) -> dict[str, Any]:
    engine = rule_engine.get_engine()
    notifier = notify_router.get_notifier()
    engine.evaluate(event)
    # insert_event uses INSERT … ON CONFLICT (event_id) DO NOTHING RETURNING
    # — `inserted` is False when the event was already in the DB, which
    # happens routinely because adapters use deterministic event_ids and
    # several ingest paths overlap on purpose (e.g. VPN agent heartbeat
    # re-ships lines the realtime follower already shipped). We only
    # notify on a genuinely new row, otherwise one auth failure becomes
    # 2–3 Slack pings.
    inserted = storage.insert_event(event)
    notified: list[dict[str, Any]]
    if not inserted:
        notified = [{"status": "duplicate", "detail": "event_id already seen"}]
    else:
        try:
            notified = notifier.dispatch(event)
        except Exception as exc:  # never let notification failure break ingest
            notified = [{"status": "error", "detail": str(exc)}]
    return {
        "event_id": event.event_id,
        "action": event.action,
        "severity": event.severity.value if event.severity else None,
        "rule_matches": event.rule_matches,
        "notified": notified,
        "duplicate": not inserted,
    }


def process_event(event: Event) -> dict[str, Any]:
    """Score, store, and route a single (already-normalized) event. Used for
    synthetic events such as staleness alerts that don't come from an adapter."""
    return _process(event)


def ingest_payload(
    module: str,
    raw: Any,
    *,
    transport: str = "webhook",
    account: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    ctx = IngestContext(module=module, transport=transport, account=account, region=region)
    adapter = registry.resolve(module)
    try:
        events = adapter.parse(raw, ctx)
    except Exception as exc:
        raise NormalizationError(str(exc)) from exc

    summaries: list[dict[str, Any]] = []
    muted = 0
    transient = 0
    for event in events:
        if noise.is_muted(event.action):  # dropped at ingest (dashboard noise control)
            muted += 1
            continue
        if event.action in _PROJECTION_ONLY_ACTIONS:
            transient += 1  # feed projection, don't store/notify
        else:
            summaries.append(_process(event))
        # Stateful projections may derive further events: transitions
        # (vpn.service.down, host.agent.recovered) and diffs (host.port.opened,
        # vpn.session.start, …). Those ARE stored — they're the signal.
        derived: list[Event] = []
        for project in _PROJECTIONS:
            try:
                derived.extend(project(event))
            except Exception as exc:
                summaries.append({"action": "projection.error", "detail": str(exc)})
        for derived_event in derived:
            if noise.is_muted(derived_event.action):
                muted += 1
                continue
            summaries.append(_process(derived_event))

    return {
        "ingested": len(summaries),
        "muted": muted,
        "transient": transient,
        "events": summaries,
    }
