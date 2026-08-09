"""UEBA per-event check. Called from the pipeline right after persist."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ..event import ActorType, Category, Event, Outcome, Severity, Source, Transport
from . import config as ueba_config
from . import db as ueba_db

_ANOMALY_INFIX = ".anomaly.first_seen_"


def _principal_of(evt: Event) -> tuple[str, str] | None:
    """Return (actor_type, principal_id) or None if the event has no real actor.
    Skips system / unknown / missing actors entirely."""
    actor = evt.actor
    if actor is None or not actor.principal:
        return None
    ptype = actor.type
    if ptype is None:
        return None
    if ptype in (ActorType.system, ActorType.unknown):
        return None
    return (ptype.value, actor.principal)


def _extract_intel(evt: Event, key: str) -> str | None:
    intel = (evt.extra or {}).get("intel")
    if isinstance(intel, dict):
        v = intel.get(key)
        if v:
            return str(v)
    return None


def _user_agent_family(evt: Event) -> str | None:
    ua = None
    if evt.actor and evt.actor.user_agent:
        ua = evt.actor.user_agent
    if not ua:
        ua = (evt.extra or {}).get("user_agent")
    if not ua:
        return None
    ua = str(ua).strip()
    if not ua:
        return None
    # Loose family: first token before "/" or space, e.g. "aws-cli/2.1" -> "aws-cli",
    # "Mozilla/5.0 ..." -> "Mozilla".
    for sep in ("/", " "):
        if sep in ua:
            return ua.split(sep, 1)[0]
    return ua


def _dimensions_for(evt: Event) -> dict[str, str]:
    out: dict[str, str] = {}
    ip = (evt.actor.source_ip if evt.actor else None)
    if ip:
        out["source_ip"] = str(ip)
    country = _extract_intel(evt, "country")
    if country:
        out["source_country"] = country
    asn = _extract_intel(evt, "asn")
    if asn:
        out["source_asn"] = str(asn)
    ts = evt.event_time or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    out["hour_of_day"] = str(ts.astimezone(timezone.utc).hour)
    if evt.action:
        out["action"] = evt.action
    ua_family = _user_agent_family(evt)
    if ua_family:
        out["user_agent_family"] = ua_family
    return out


def _make_anomaly_event(
    src: Event, dimension: str, value: str, ptype: str, pid: str,
) -> Event:
    cat_value = src.category.value if isinstance(src.category, Category) else str(src.category)
    action = f"{cat_value}{_ANOMALY_INFIX}{dimension}"
    return Event(
        source=Source(
            module=src.source.module,
            vendor=src.source.vendor,
            account=src.source.account,
            region=src.source.region,
            transport=Transport.api,
        ),
        event_time=src.event_time,
        category=src.category,
        action=action,
        outcome=Outcome.unknown,
        actor=src.actor,
        target=src.target,
        severity=Severity.medium,
        tags=["ueba", "first-seen", f"dim:{dimension}"],
        extra={
            "trigger_event_id": src.event_id,
            "trigger_action": src.action,
            "principal_type": ptype,
            "principal_id": pid,
            "dimension": dimension,
            "baseline_value": value,
        },
    )


def check_event(evt: Event, emit_fn: Callable[[Event], Any]) -> None:
    """Update baselines from `evt` and emit anomaly events via `emit_fn` for
    any dimension where a new value appears past the warm-up window.

    Idempotency: the anomaly event has a deterministic dedup fingerprint via
    action+principal, and the baseline row itself only reaches count==1 once,
    so replays of the same source event cannot fire a second anomaly."""
    # Never react to our own synthetic anomaly events.
    if _ANOMALY_INFIX in (evt.action or ""):
        return
    principal = _principal_of(evt)
    if principal is None:
        return
    ptype, pid = principal

    cfg = ueba_config.load()
    if not cfg.principal_allowed(ptype):
        return

    dims = _dimensions_for(evt)
    if not dims:
        return

    ts = evt.event_time or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now_ts = int(ts.timestamp())

    first_ever = ueba_db.get_or_create_first_seen(ptype, pid, now_ts)

    for dim_name, value in dims.items():
        dcfg = cfg.dim(dim_name)
        if not dcfg.enabled:
            continue
        count = ueba_db.upsert_baseline(ptype, pid, dim_name, value, now_ts)
        # Warm-up: silently populate until the principal is old enough.
        warm_up_secs = int(dcfg.warm_up_days) * 86400
        if (now_ts - first_ever) < warm_up_secs:
            continue
        if count != 1:
            continue  # already seen this value at least once before
        anomaly = _make_anomaly_event(evt, dim_name, value, ptype, pid)
        try:
            emit_fn(anomaly)
        except Exception:
            # Never let a downstream failure abort further dimension checks.
            continue
