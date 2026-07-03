"""ECS service projection.

Consumes events from the ecs.probe adapter and maintains `service_status` +
`probe_agent_status`. The job split:

  * `probe.agent.heartbeat` -> upsert probe_agent_status with last_report.
    Emits `probe.agent.first_seen` on the first-ever heartbeat for a VPC and
    `probe.agent.recovered` when a stale agent reports again.

  * `service.probe.result`  -> compare each result vs. the stored status,
    apply hysteresis (require N consecutive failures to declare down, 1 success
    to recover), and emit transition events.

Hysteresis matters here: HTTP probes flap on transient network blips. Without
this, every minor jitter pages someone. With it, a single bad probe is silently
absorbed; only sustained failure escalates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Category, Event, Outcome, Source, Target, Transport

_MODULE = "ecs.probe"


def _friendly_service_message(action: str, vpc: str, name: str,
                              error: str | None) -> str:
    """Produce a Slack/Discord-friendly headline so alerts don't read as
    `service.down on api`. We include VPC + service name + a short hint
    about the failure mode so the recipient can triage without opening BW."""
    err_l = (error or "").lower()
    if action == "service.down":
        if "timed out" in err_l or "timeout" in err_l:
            hint = "timeout"
        elif "refused" in err_l or "reset" in err_l:
            hint = "connection refused"
        elif "name or service not known" in err_l or "name resolution" in err_l:
            hint = "DNS lookup failed"
        elif error and error.startswith("HTTP 5"):
            hint = error
        elif error:
            hint = error[:60]
        else:
            hint = "no response"
        return f"{vpc}: {name} went DOWN ({hint})"
    if action == "service.degraded":
        suffix = f" ({error})" if error else ""
        return f"{vpc}: {name} is degraded{suffix}"
    if action == "service.up":
        return f"{vpc}: {name} recovered (UP)"
    return action

# How many consecutive failed probes before declaring a target `down`.
# 2 = first jitter absorbed, second confirms — fast enough but kills noise.
DOWN_THRESHOLD = 2
# How many consecutive successes before declaring `up` (after being down/degraded).
# Symmetric with DOWN_THRESHOLD — a flapping service that succeeds once and
# fails twice would otherwise emit `service.up` on every single successful
# probe, spamming the channel. Requiring 2 consecutive successes means
# recovery only fires when the service actually stabilised.
UP_THRESHOLD = 2


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    if event.action == "probe.agent.heartbeat":
        return _project_heartbeat(event)
    if event.action == "service.probe.result":
        return _project_result(event)
    return []


# ---------- probe.agent.heartbeat -------------------------------------------

def _project_heartbeat(event: Event) -> list[Event]:
    vpc = event.extra.get("vpc") or (event.target.id if event.target else None)
    if not vpc:
        return []
    when = event.event_time or datetime.now(timezone.utc)
    prev = storage.get_probe_agent(vpc)
    prev_active = prev["active"] if prev else None
    storage.upsert_probe_agent(
        vpc,
        last_report=when,
        agent_version=event.extra.get("agent_version"),
        active=True,
    )
    if prev_active is None:
        return [_derive(event, "probe.agent.first_seen", vpc, {"vpc": vpc}, when)]
    if prev_active is False:
        return [_derive(event, "probe.agent.recovered", vpc, {"vpc": vpc}, when)]
    return []


# ---------- service.probe.result --------------------------------------------

def _project_result(event: Event) -> list[Event]:
    e = event.extra
    target_id = e.get("target_id")
    if not target_id:
        return []
    vpc = e.get("vpc") or "unknown"
    name = e.get("name") or target_id
    tier = e.get("tier") or "unknown"
    incoming_status = e.get("status") or "unknown"
    latency_ms = e.get("latency_ms")
    when = event.event_time or datetime.now(timezone.utc)

    prev = storage.get_service_status(target_id)
    prev_status = prev["status"] if prev else None
    fails = (prev["consecutive_fails"] if prev else 0)
    succs = (prev["consecutive_success"] if prev else 0)
    prev_down_since = (prev.get("down_since") if prev else None)

    # Hysteresis bookkeeping. `unknown` resets both counters since it
    # represents indeterminate state -- neither "this attempt confirmed
    # down" nor "this attempt confirmed up", so prior fails/successes
    # no longer mean anything definite.
    if incoming_status == "up":
        succs += 1; fails = 0
    elif incoming_status in ("down", "degraded"):
        fails += 1; succs = 0
    else:  # 'unknown'
        fails = 0; succs = 0

    # Decide what the *effective* status should be after hysteresis.
    effective = prev_status if prev_status else incoming_status
    if incoming_status == "up" and succs >= UP_THRESHOLD:
        effective = "up"
    elif incoming_status in ("down", "degraded") and fails >= DOWN_THRESHOLD:
        effective = incoming_status
    elif incoming_status == "unknown":
        # Unknown takes effect immediately -- no hysteresis. It's not a
        # signal we're confident enough to delay; it IS the confidence level.
        effective = "unknown"

    # Track how long the service has been continuously down. Set on the
    # transition INTO down/degraded (so it survives subsequent down probes),
    # cleared on transition back to up. Lazy-backfill for pre-migration rows
    # that came up as down without ever crossing the edge.
    if effective in ("down", "degraded"):
        down_since = prev_down_since or when
    else:
        down_since = None

    storage.upsert_service_status(
        target_id, vpc=vpc, name=name, tier=tier,
        status=effective, last_seen=when, latency_ms=latency_ms,
        consecutive_fails=fails, consecutive_success=succs,
        down_since=down_since,
        extra={
            "last_raw_status": incoming_status,
            "last_error": e.get("error"),
            "tier_extra": e.get("result_extra") or {},
        },
    )

    derived: list[Event] = []
    if prev_status != effective:
        # Transitioned. Emit the right action.
        action = {
            "up": "service.up",
            "down": "service.down",
            "degraded": "service.degraded",
        }.get(effective)
        if action:
            extras = {
                "vpc": vpc, "name": name, "tier": tier,
                "target_id": target_id, "prev_status": prev_status,
                "status": effective, "latency_ms": latency_ms,
                "error": e.get("error"),
                # Friendly headline -- the notification templates render
                # `event.extra.message` ahead of `event.action`, so this is
                # what shows up in Slack/Discord/Teams.
                "message": _friendly_service_message(action, vpc, name, e.get("error")),
            }
            # Promote target's tags onto the derived event so per-env routing
            # works (e.g. service-down-prod-critical rule).
            target_row = storage.get_probe_target(target_id)
            if target_row:
                extras["tags"] = target_row.get("tags") or {}
            derived.append(_derive(event, action, target_id, extras, when,
                                    target_type="ecs.service", target_name=name))
    return derived


def _derive(
    parent: Event, action: str, target_id: str, extra: dict[str, Any],
    when: datetime, *, target_type: str = "probe.agent", target_name: str | None = None,
) -> Event:
    return Event(
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=when,
        category=Category.other,
        action=action,
        outcome=(Outcome.success if action.endswith(".up") or action.endswith(".recovered")
                 or action.endswith(".first_seen") else Outcome.failure),
        target=Target(id=target_id, type=target_type, name=target_name or target_id),
        extra=extra,
        raw={"derived_from": parent.action, "module": _MODULE},
    )
