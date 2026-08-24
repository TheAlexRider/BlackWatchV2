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
from ..event import Category, Event, Outcome, Severity, Source, Target, Transport

_MODULE = "ecs.probe"


# --- severity + message helpers ---------------------------------------------
#
# The projection sets both the severity and the pre-formatted body on every
# derived event. The channel templates (Slack/Discord/Teams) render
# `event.extra.message` verbatim when set, so what we build here IS what the
# operator sees — no per-rule template needed.

def _is_prod(tags: dict[str, Any] | None) -> bool:
    """Prod bias — checked against the target's tags. `env=prod` bumps
    service.down to critical and service.degraded to high so operators can
    set up one route ("high or above") and only get paged on real prod
    problems."""
    if not isinstance(tags, dict):
        return False
    v = str(tags.get("env") or "").strip().lower()
    return v in ("prod", "production")


def _ecs_severity(action: str, tags: dict[str, Any] | None) -> Severity:
    """Severity per event type. Recovery/first-seen events stay quiet so a
    "high or above" route only pages on real outages."""
    prod = _is_prod(tags)
    if action == "service.down":
        return Severity.critical if prod else Severity.high
    if action == "service.degraded":
        return Severity.high if prod else Severity.medium
    if action == "service.unknown":
        # Monitoring uncertainty is not a confirmed outage, but sustained
        # inability to reach a production target is still high-signal.
        return Severity.high if prod else Severity.medium
    if action == "probe.agent.stale":
        return Severity.critical  # whole VPC's probe visibility is offline
    if action in ("service.up", "probe.agent.recovered"):
        return Severity.informational
    if action == "probe.agent.first_seen":
        return Severity.informational
    return Severity.informational


def _fmt_ts(when: datetime | None) -> str:
    if when is None:
        return "—"
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m} min"
    h = m // 60
    rem = m % 60
    return f"{h}h {rem}m" if rem else f"{h}h"


def _down_hint(error: str | None) -> str:
    """Human-friendly summary of why a probe failed. Feeds the "Error" line
    of service.down messages so the reader can triage without leaving Slack."""
    err_l = (error or "").lower()
    if "timed out" in err_l or "timeout" in err_l:
        return "timeout"
    if "refused" in err_l or "reset" in err_l:
        return "connection refused"
    if "name or service not known" in err_l or "name resolution" in err_l:
        return "DNS lookup failed"
    if error and error.startswith("HTTP 5"):
        return error
    if error:
        return error[:80]
    return "no response"


def _friendly_service_message(
    action: str,
    vpc: str,
    name: str,
    error: str | None,
    *,
    tags: dict[str, Any] | None = None,
    when: datetime | None = None,
    down_since: datetime | None = None,
    down_seconds: float | None = None,
    unknown_seconds: float | None = None,
    latency_ms: int | None = None,
) -> str:
    """Build the pre-formatted Slack/Discord/Teams body for an ECS lifecycle
    event. Multi-line markdown — the channel template passes it through
    verbatim so what you see here is what lands in the channel.

    The kwargs are optional so older callers keep working; when the projection
    supplies them (down_since, latency, etc.), the body gets richer."""
    env_line = ""
    if isinstance(tags, dict):
        env_val = tags.get("env")
        if env_val:
            env_line = f"• *Env:* {env_val}\n"

    if action == "service.down":
        hint = _down_hint(error)
        lines = [f"*{name} went DOWN*"]
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"• *VPC:* {vpc}")
        lines.append(f"• *Error:* {hint}")
        if down_since is not None:
            lines.append(f"• *Since:* {_fmt_ts(down_since)}")
        if env_line:
            lines.append(env_line.rstrip("\n"))
        return "\n".join(lines)

    if action == "service.degraded":
        lines = [f"*{name} is degraded*"]
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"• *VPC:* {vpc}")
        if error:
            lines.append(f"• *Signal:* {error}")
        if latency_ms is not None:
            lines.append(f"• *Latency:* {latency_ms} ms")
        if env_line:
            lines.append(env_line.rstrip("\n"))
        return "\n".join(lines)

    if action == "service.up":
        lines = [f"*{name} recovered*"]
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"• *VPC:* {vpc}")
        if down_seconds is not None and down_seconds > 0:
            lines.append(f"• *Was down for:* {_fmt_duration(down_seconds)}")
        if unknown_seconds is not None and unknown_seconds > 0:
            lines.append(f"• *Monitoring was uncertain for:* {_fmt_duration(unknown_seconds)}")
        if latency_ms is not None:
            lines.append(f"• *Latency now:* {latency_ms} ms")
        if env_line:
            lines.append(env_line.rstrip("\n"))
        return "\n".join(lines)

    if action == "service.unknown":
        lines = [f"*Unable to verify {name}*"]
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"• *VPC:* {vpc}")
        lines.append("• *Signal:* probe could not determine service availability")
        if error:
            lines.append(f"• *Reason:* {_down_hint(error)}")
        if env_line:
            lines.append(env_line.rstrip("\n"))
        return "\n".join(lines)

    if action == "probe.agent.first_seen":
        return (
            f"*New probe agent seen in `{vpc}`*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• *First report:* {_fmt_ts(when)}"
        )

    if action == "probe.agent.recovered":
        return (
            f"*Probe agent recovered in `{vpc}`*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Reporting again as of:* {_fmt_ts(when)}"
        )

    # probe.agent.stale is built in staleness.py — kept there because it has
    # access to age_seconds; we only fall through here for unknown actions.
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
# A network/DNS failure is not proof that the service is down. Alert only when
# the target has remained unverifiable for ten minutes, independent of the
# probe interval.
UNKNOWN_AFTER_SECONDS = 10 * 60


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
        return [_derive(
            event, "probe.agent.first_seen", vpc,
            {
                "vpc": vpc,
                "message": _friendly_service_message(
                    "probe.agent.first_seen", vpc, vpc, None, when=when,
                ),
            },
            when,
        )]
    if prev_active is False:
        return [_derive(
            event, "probe.agent.recovered", vpc,
            {
                "vpc": vpc,
                "message": _friendly_service_message(
                    "probe.agent.recovered", vpc, vpc, None, when=when,
                ),
            },
            when,
        )]
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
    prev_extra = (prev.get("extra") or {}) if prev else {}
    unknown_since = prev_extra.get("unknown_since")
    unknown_streak = int(prev_extra.get("unknown_streak") or 0)
    unknown_alerted = bool(prev_extra.get("unknown_alerted"))

    # Hysteresis bookkeeping. `unknown` resets both counters since it
    # represents indeterminate state -- neither "this attempt confirmed
    # down" nor "this attempt confirmed up", so prior fails/successes
    # no longer mean anything definite.
    if incoming_status == "up":
        succs += 1; fails = 0
        unknown_streak = 0
    elif incoming_status in ("down", "degraded"):
        fails += 1; succs = 0
        unknown_streak = 0
    else:  # 'unknown'
        fails = 0; succs = 0
        unknown_streak += 1
        if unknown_since is None:
            unknown_since = when.isoformat()

    unknown_duration = 0.0
    if unknown_since is not None:
        try:
            unknown_duration = max(
                0, (when - datetime.fromisoformat(unknown_since)).total_seconds()
            )
        except (TypeError, ValueError):
            unknown_duration = 0.0
    unknown_ready = unknown_duration >= UNKNOWN_AFTER_SECONDS

    # Decide what the *effective* status should be after hysteresis.
    effective = prev_status if prev_status else incoming_status
    if incoming_status == "up" and succs >= UP_THRESHOLD:
        effective = "up"
    elif incoming_status in ("down", "degraded") and fails >= DOWN_THRESHOLD:
        effective = incoming_status
    elif incoming_status == "unknown":
        # Network uncertainty gets a small amount of hysteresis. Preserve an
        # already-known status for one failed probe, then surface the unknown
        # state when it persists. This avoids paging on one transient timeout.
        effective = "unknown" if unknown_ready else (prev_status or "unknown")

    # Track how long the service has been continuously down. Set on the
    # transition INTO down/degraded (so it survives subsequent down probes),
    # cleared on transition back to up. Lazy-backfill for pre-migration rows
    # that came up as down without ever crossing the edge.
    if effective in ("down", "degraded"):
        down_since = prev_down_since or when
    else:
        down_since = None

    state_extra = {
        "last_raw_status": incoming_status,
        "last_error": e.get("error"),
        "tier_extra": e.get("result_extra") or {},
    }
    if incoming_status == "unknown" or effective == "unknown":
        state_extra["unknown_since"] = unknown_since
        state_extra["unknown_streak"] = unknown_streak
        state_extra["unknown_alerted"] = unknown_alerted or unknown_ready

    storage.upsert_service_status(
        target_id, vpc=vpc, name=name, tier=tier,
        status=effective, last_seen=when, latency_ms=latency_ms,
        consecutive_fails=fails, consecutive_success=succs,
        down_since=down_since,
        extra=state_extra,
    )

    derived: list[Event] = []
    emits_unknown = (
        effective == "unknown"
        and unknown_ready
        and not unknown_alerted
    )
    if prev_status != effective or emits_unknown:
        # Transitioned. Emit the right action.
        action = {
            "up": "service.up",
            "down": "service.down",
            "degraded": "service.degraded",
            "unknown": "service.unknown",
        }.get(effective)
        # Do not send a recovery for a single/unalerted unknown result. A
        # recovery pairs with an emitted unknown alert, just as a normal
        # recovery pairs with a real down/degraded transition.
        if action == "service.up" and prev_status == "unknown" and not unknown_alerted:
            action = None
        if action:
            # Promote target's tags onto the derived event so per-env routing
            # works (e.g. service-down-prod-critical rule) AND so the severity
            # helper can bias by env=prod.
            target_row = storage.get_probe_target(target_id)
            target_tags = (target_row.get("tags") or {}) if target_row else {}

            # For service.up, compute how long the outage lasted so the
            # recovery message can say "was down for 12 min".
            down_seconds: float | None = None
            if action == "service.up" and prev_down_since is not None:
                try:
                    down_seconds = (when - prev_down_since).total_seconds()
                except Exception:
                    down_seconds = None

            unknown_seconds: float | None = None
            if action == "service.up" and prev_status == "unknown" and unknown_since:
                try:
                    unknown_seconds = max(
                        0, (when - datetime.fromisoformat(unknown_since)).total_seconds()
                    )
                except (TypeError, ValueError):
                    unknown_seconds = None

            extras = {
                "vpc": vpc, "name": name, "tier": tier,
                "target_id": target_id, "prev_status": prev_status,
                "status": effective, "latency_ms": latency_ms,
                "error": e.get("error"),
                # Pre-formatted body — the Slack/Discord/Teams channel
                # templates use this verbatim (see notify/channels.py).
                "message": _friendly_service_message(
                    action, vpc, name, e.get("error"),
                    tags=target_tags,
                    when=when,
                    down_since=prev_down_since,
                    down_seconds=down_seconds,
                    unknown_seconds=unknown_seconds,
                    latency_ms=latency_ms,
                ),
            }
            if target_tags:
                extras["tags"] = target_tags
            if down_seconds is not None:
                extras["down_seconds"] = int(down_seconds)
            if unknown_seconds is not None:
                extras["unknown_seconds"] = int(unknown_seconds)

            derived.append(_derive(
                event, action, target_id, extras, when,
                target_type="ecs.service", target_name=name,
                severity=_ecs_severity(action, target_tags),
            ))
    return derived


def _derive(
    parent: Event, action: str, target_id: str, extra: dict[str, Any],
    when: datetime, *, target_type: str = "probe.agent",
    target_name: str | None = None,
    severity: Severity | None = None,
) -> Event:
    # Severity default: compute from the action + tags on the extra if the
    # caller didn't pass one. Keeps _project_heartbeat calls one-liner.
    if severity is None:
        severity = _ecs_severity(action, extra.get("tags") if isinstance(extra, dict) else None)
    return Event(
        source=Source(module=_MODULE, transport=Transport.api),
        event_time=when,
        category=Category.other,
        action=action,
        outcome=(Outcome.success if action.endswith(".up") or action.endswith(".recovered")
                 or action.endswith(".first_seen") else Outcome.failure),
        severity=severity,
        target=Target(id=target_id, type=target_type, name=target_name or target_id),
        extra=extra,
        raw={"derived_from": parent.action, "module": _MODULE},
    )
