"""API Gateway projection.

Consumes events from the aws.api_gw adapter, maintains api_sources, and
emits derived detection events:

  * api.request         -> upsert source_ip / api_name row.
                           First-seen (source_ip) emits api.source.new.
  * api.auth.failure    -> counts recent 4xx auth failures per source_ip;
                           when the Nth failure trips the burst threshold,
                           emits api.auth.burst once per (ip, minute).
  * api.error           -> counts recent 5xx per source_ip; burst emits
                           api.error.burst (upstream / integration outage
                           targeting one client, rare but useful).

`api.scanner_ua` is emitted by the adapter and NOT further projected —
the raw event is already the alert.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import storage
from ..event import Actor, Category, Event, Outcome, Source, Target, Transport

_MODULE = "aws.api_gw"

# Burst threshold tuned for a healthcare API. 10 auth failures in 5 min from
# one client IP is well past legitimate-user retry territory.
AUTH_BURST_THRESHOLD = 10
AUTH_BURST_WINDOW_MINUTES = 5

# 5xx spikes are usually server-side and not a security event on their own,
# but a burst tied to a single client can indicate targeted probing (e.g.
# fuzzing that trips backend exceptions). Threshold is looser here.
ERROR_BURST_THRESHOLD = 25
ERROR_BURST_WINDOW_MINUTES = 5


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    action = event.action
    e = event.extra or {}
    ts = event.event_time or datetime.now(timezone.utc)

    if action == "api.request":
        return _record_source(event, ts)

    if action == "api.auth.failure":
        return _detect_auth_burst(event, ts)

    if action == "api.error":
        return _detect_error_burst(event, ts)

    return []


# --- api.request → source tracking + first-seen alert ---------------------

def _record_source(event: Event, ts: datetime) -> list[Event]:
    e = event.extra or {}
    ip = e.get("source_ip") or (event.actor.source_ip if event.actor else None)
    if not ip:
        return []
    api_name = e.get("api_name") or "unknown"
    status = int(e.get("status") or 0)
    is_4xx = 400 <= status < 500
    is_5xx = 500 <= status < 600
    try:
        is_new = storage.upsert_api_source(
            ip, api_name, ts, is_4xx=is_4xx, is_5xx=is_5xx,
        )
    except Exception:
        return []
    if not is_new:
        return []
    day = ts.strftime("%Y%m%d")
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"api.source.new::{ip}::{day}"))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="api.source.new",
        outcome=Outcome.failure,
        actor=Actor(principal=None, source_ip=ip),
        target=Target(id=api_name, type="api.gateway", name=api_name),
        extra={
            "api_name": api_name,
            "source_ip": ip,
            "tags": {"env": "prod", "api": api_name},
            "message": (
                f"{api_name}: new source IP {ip} touched the API Gateway — "
                "never seen before"
            ),
        },
        raw={"derived_from": "api.request"},
    )]


# --- api.auth.failure burst detection --------------------------------------

def _detect_auth_burst(event: Event, ts: datetime) -> list[Event]:
    """Count recent api.auth.failure events for this source IP. When the count
    hits the threshold exactly, emit api.auth.burst once per (ip, minute) so
    we don't re-fire every subsequent failure in the same window."""
    e = event.extra or {}
    ip = e.get("source_ip") or (event.actor.source_ip if event.actor else None)
    if not ip:
        return []
    api_name = e.get("api_name") or "unknown"
    since = ts - timedelta(minutes=AUTH_BURST_WINDOW_MINUTES)
    try:
        recent = storage.query_events(
            module=_MODULE, action="api.auth.failure",
            actor_source_ip=ip, since=since, limit=AUTH_BURST_THRESHOLD + 5,
        )
    except Exception:
        return []
    if len(recent) != AUTH_BURST_THRESHOLD:
        return []
    minute = ts.strftime("%Y%m%d%H%M")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"api.auth.burst::{api_name}::{ip}::{minute}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="api.auth.burst",
        outcome=Outcome.failure,
        actor=Actor(principal=None, source_ip=ip),
        target=Target(id=api_name, type="api.gateway", name=api_name),
        extra={
            "api_name": api_name,
            "source_ip": ip,
            "failure_count": len(recent),
            "window_minutes": AUTH_BURST_WINDOW_MINUTES,
            "tags": {"env": "prod", "api": api_name},
            "message": (
                f"{api_name}: {AUTH_BURST_THRESHOLD}+ auth failures from "
                f"{ip} in {AUTH_BURST_WINDOW_MINUTES} min "
                "— possible credential stuffing"
            ),
        },
        raw={"derived_from": "api.auth.failure"},
    )]


def _detect_error_burst(event: Event, ts: datetime) -> list[Event]:
    e = event.extra or {}
    ip = e.get("source_ip") or (event.actor.source_ip if event.actor else None)
    if not ip:
        return []
    api_name = e.get("api_name") or "unknown"
    since = ts - timedelta(minutes=ERROR_BURST_WINDOW_MINUTES)
    try:
        recent = storage.query_events(
            module=_MODULE, action="api.error",
            actor_source_ip=ip, since=since, limit=ERROR_BURST_THRESHOLD + 5,
        )
    except Exception:
        return []
    if len(recent) != ERROR_BURST_THRESHOLD:
        return []
    minute = ts.strftime("%Y%m%d%H%M")
    event_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"api.error.burst::{api_name}::{ip}::{minute}",
    ))
    return [Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=ts,
        category=Category.other,
        action="api.error.burst",
        outcome=Outcome.failure,
        actor=Actor(principal=None, source_ip=ip),
        target=Target(id=api_name, type="api.gateway", name=api_name),
        extra={
            "api_name": api_name,
            "source_ip": ip,
            "error_count": len(recent),
            "window_minutes": ERROR_BURST_WINDOW_MINUTES,
            "tags": {"env": "prod", "api": api_name},
            "message": (
                f"{api_name}: {ERROR_BURST_THRESHOLD}+ 5xx errors on requests "
                f"from {ip} in {ERROR_BURST_WINDOW_MINUTES} min "
                "— possible fuzzing or backend outage on one client"
            ),
        },
        raw={"derived_from": "api.error"},
    )]
