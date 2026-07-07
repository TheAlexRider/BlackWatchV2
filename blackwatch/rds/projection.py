"""RDS session projection.

Consumes events from the aws.rds adapter, maintains rds_active_sessions,
and emits a few derived detection events:

  * rds.session.start          -> INSERT (or refresh last_seen_at).
                                  Checks for concurrent sessions across
                                  multiple source IPs -> rds.session.concurrent.
                                  Also: if we have a real_client_ip (pinned
                                  session via proxy), first-seen (user, ip)
                                  emits rds.session.new_source.
                                  Any user not on the allowlist emits
                                  rds.user.unknown.
  * rds.session.end            -> mark disconnected, record duration.
  * rds.auth.failure           -> counts recent failures for the same user
                                  in the last N minutes; the Nth failure
                                  tips into rds.auth.burst. Also: any user
                                  not on the allowlist -> rds.user.unknown.
  * rds.proxy.client.connect   -> record the real client IP in
                                  rds_proxy_sources; first-seen fires
                                  rds.proxy.source.new.

Long-idle session detection lives in blackwatch/rds/staleness.py (periodic
sweep) because it's timer-driven, not event-driven.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import storage
from ..event import Actor, Category, Event, Outcome, Source, Target, Transport

_MODULE = "aws.rds"

# --- Detection thresholds ---------------------------------------------------
# Number of failed auth events per user within BURST_WINDOW_MINUTES that
# escalates to a burst alert. Tuned to catch human brute-forcing and simple
# script attacks without alerting on the occasional pool reconnection glitch.
BURST_THRESHOLD = 5
BURST_WINDOW_MINUTES = 5


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    action = event.action
    e = event.extra or {}
    ts = event.event_time or datetime.now(timezone.utc)

    if action == "rds.session.start":
        session_id = e.get("session_id")
        if not session_id:
            return []
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
                extra={
                    "backend_pid": e.get("backend_pid"),
                    "real_client_ip": e.get("real_client_ip"),
                    "real_client_port": e.get("real_client_port"),
                },
            )
        except Exception:
            return []
        derived = _detect_concurrent(event, ts)
        derived.extend(_detect_unknown_user(event, ts))
        derived.extend(_detect_new_user_source(event, ts))
        return derived

    if action == "rds.session.end":
        session_id = e.get("session_id")
        if not session_id:
            return []
        try:
            storage.close_rds_session(
                session_id,
                disconnected_at=ts,
                duration_seconds=e.get("duration_seconds"),
            )
        except Exception:
            pass
        return []

    if action == "rds.auth.failure":
        derived = _detect_burst(event, ts)
        derived.extend(_detect_unknown_user(event, ts))
        return derived

    if action == "rds.proxy.client.connect":
        return _record_proxy_source(event, ts)

    return []


# --- Concurrent-session detection ------------------------------------------

def _detect_concurrent(event: Event, ts: datetime) -> list[Event]:
    """After inserting a new session, look for other open sessions for the
    same user with a DIFFERENT source IP. That's the credential-sharing /
    credential-theft signal. One event per (user, day) to avoid re-firing
    every time the same user opens a new pool connection."""
    e = event.extra or {}
    user = e.get("user")
    db_instance = e.get("db_instance") or "unknown"
    source_ip = e.get("source_ip")
    if not user or not source_ip:
        return []
    try:
        active = storage.list_rds_active_sessions(db_instance=db_instance, limit=500)
    except Exception:
        return []
    other_ips = {
        s.get("source_ip") for s in active
        if s.get("db_user") == user and s.get("source_ip")
        and s.get("source_ip") != source_ip
    }
    if not other_ips:
        return []
    ips_sorted = sorted(other_ips | {source_ip})
    day = ts.strftime("%Y%m%d")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rds.session.concurrent::{db_instance}::{user}::{day}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="rds.session.concurrent",
        outcome=Outcome.failure,
        actor=Actor(principal=user, source_ip=source_ip),
        target=Target(id=db_instance, type="rds.db", name=db_instance),
        extra={
            "db_instance": db_instance,
            "user": user,
            "source_ips": ips_sorted,
            "tags": {"env": "prod", "db_instance": db_instance},
            "message": (
                f"{db_instance}: {user} is connected from multiple IPs "
                f"simultaneously ({', '.join(ips_sorted)})"
            ),
        },
        raw={"derived_from": "rds.session.start"},
    )]


# --- Auth-failure burst detection ------------------------------------------

def _detect_burst(event: Event, ts: datetime) -> list[Event]:
    """Count rds.auth.failure events for this user in the last BURST_WINDOW.
    When the count hits BURST_THRESHOLD exactly, emit rds.auth.burst once.
    Subsequent failures in the same window don't re-fire; they're already
    covered by the initial burst event's notification dedup."""
    e = event.extra or {}
    user = e.get("user") or (event.actor.principal if event.actor else None)
    db_instance = e.get("db_instance") or "unknown"
    if not user:
        return []
    since = ts - timedelta(minutes=BURST_WINDOW_MINUTES)
    try:
        recent = storage.query_events(
            module=_MODULE, action="rds.auth.failure",
            actor_principal=user, since=since, limit=BURST_THRESHOLD + 5,
        )
    except Exception:
        return []
    # We include the just-inserted event in the count (projections run after
    # storage.insert_event). Fire on the exact tipping point.
    if len(recent) != BURST_THRESHOLD:
        return []
    source_ips = sorted({
        (r.get("actor_source_ip") or (r.get("extra") or {}).get("source_ip"))
        for r in recent
    } - {None})
    minute = ts.strftime("%Y%m%d%H%M")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rds.auth.burst::{db_instance}::{user}::{minute}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="rds.auth.burst",
        outcome=Outcome.failure,
        actor=Actor(
            principal=user,
            source_ip=(event.actor.source_ip if event.actor else None),
        ),
        target=Target(id=db_instance, type="rds.db", name=db_instance),
        extra={
            "db_instance": db_instance,
            "user": user,
            "failure_count": len(recent),
            "window_minutes": BURST_WINDOW_MINUTES,
            "source_ips": source_ips,
            "tags": {"env": "prod", "db_instance": db_instance},
            "message": (
                f"{db_instance}: {BURST_THRESHOLD}+ failed logins for "
                f"{user} in {BURST_WINDOW_MINUTES} min "
                f"(from {', '.join(source_ips) if source_ips else 'unknown'})"
            ),
        },
        raw={"derived_from": "rds.auth.failure"},
    )]


# --- Shape B detectors ------------------------------------------------------

def _record_proxy_source(event: Event, ts: datetime) -> list[Event]:
    """Every rds.proxy.client.connect carries a real client IP. Record it in
    rds_proxy_sources; if this is the first time we've ever seen this IP,
    emit rds.proxy.source.new. That's the "unusual IP touched the proxy"
    signal — VPN cert compromise, unrecognized laptop, etc."""
    e = event.extra or {}
    ip = e.get("source_ip") or (event.actor.source_ip if event.actor else None)
    if not ip:
        return []
    try:
        is_new = storage.upsert_rds_proxy_source(ip, ts)
    except Exception:
        return []
    if not is_new:
        return []
    db_instance = e.get("db_instance") or "unknown"
    day = ts.strftime("%Y%m%d")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rds.proxy.source.new::{ip}::{day}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="rds.proxy.source.new",
        outcome=Outcome.failure,
        actor=Actor(principal=None, source_ip=ip),
        target=Target(id=db_instance, type="rds.db", name=db_instance),
        extra={
            "db_instance": db_instance,
            "source_ip": ip,
            "tags": {"env": "prod", "db_instance": db_instance},
            "message": (
                f"{db_instance}: new source IP {ip} connected to the RDS "
                f"Proxy — never seen before"
            ),
        },
        raw={"derived_from": "rds.proxy.client.connect"},
    )]


def _detect_new_user_source(event: Event, ts: datetime) -> list[Event]:
    """When we successfully traced a postgres session back to its real
    client IP (via the proxy pinning chain), record (user, real_ip) and
    fire when the pair is first-seen. This is the credential-theft-from-
    unusual-location signal."""
    e = event.extra or {}
    user = e.get("user")
    real_ip = e.get("real_client_ip")
    if not user or not real_ip:
        return []
    try:
        is_new = storage.upsert_rds_user_source(user, real_ip, ts)
    except Exception:
        return []
    if not is_new:
        return []
    db_instance = e.get("db_instance") or "unknown"
    day = ts.strftime("%Y%m%d")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rds.session.new_source::{db_instance}::{user}::{real_ip}::{day}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="rds.session.new_source",
        outcome=Outcome.failure,
        actor=Actor(principal=user, source_ip=real_ip),
        target=Target(id=db_instance, type="rds.db", name=db_instance),
        extra={
            "db_instance": db_instance,
            "user": user,
            "source_ip": real_ip,
            "tags": {"env": "prod", "db_instance": db_instance},
            "message": (
                f"{db_instance}: {user} connected from a new source IP "
                f"({real_ip}) — never seen for this user before"
            ),
        },
        raw={"derived_from": "rds.session.start"},
    )]


def _detect_unknown_user(event: Event, ts: datetime) -> list[Event]:
    """Fires when someone authenticates (success or fail) as a username
    that isn't on the operator's allowlist. Cheapest possible offboarding
    detector — no baseline, no ML, just a list. One event per (user, day)
    to avoid re-firing on every reconnection."""
    e = event.extra or {}
    user = e.get("user") or (event.actor.principal if event.actor else None)
    if not user:
        return []
    try:
        if storage.is_rds_user_allowlisted(user):
            return []
    except Exception:
        return []
    db_instance = e.get("db_instance") or "unknown"
    day = ts.strftime("%Y%m%d")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rds.user.unknown::{db_instance}::{user}::{day}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="rds.user.unknown",
        outcome=Outcome.failure,
        actor=Actor(
            principal=user,
            source_ip=(event.actor.source_ip if event.actor else None),
        ),
        target=Target(id=db_instance, type="rds.db", name=db_instance),
        extra={
            "db_instance": db_instance,
            "user": user,
            "trigger": event.action,
            "tags": {"env": "prod", "db_instance": db_instance},
            "message": (
                f"{db_instance}: DB user {user!r} is not on the allowlist "
                f"(triggered by {event.action})"
            ),
        },
        raw={"derived_from": event.action},
    )]
