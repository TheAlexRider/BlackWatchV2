"""Performance alert evaluator.

Runs on every host heartbeat (host.service.health). For each enabled rule
that matches this instance (directly via instance_id, or via tag_key=tag_value):

  1. Extract the relevant metric from heartbeat.extra.
  2. Append a sample to the rule's rolling window buffer.
  3. Trim samples older than window_seconds.
  4. If the breach ratio over the window meets min_breach_ratio, fire:
       - emit a synthetic host.perf.alert event (for /events visibility)
       - dispatch directly to the rule's bound channels (the user picked
         them at rule creation; no need for a separate notification rule)
       - record last_fired_at and respect throttle_seconds for re-fires.

Looser semantics by design (you asked for it): the user thinks "memory >80%
for 5 minutes," internally we tolerate dips — at min_breach_ratio=0.6 a
single sample below threshold mid-window doesn't reset the counter. The
notification message reads as duration, matching the user's mental model
("Memory ≥ 80% for 5m (current: 87.2%)").
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jinja2 import Environment, StrictUndefined

from . import storage
from .event import Category, Event, Outcome

_jinja = Environment(autoescape=False, undefined=StrictUndefined, trim_blocks=True)


def _render_message(template: str | None, fallback: str, ctx: dict[str, Any]) -> str:
    """Render a per-rule Jinja template with the alert context. Any error
    (bad syntax, missing var, exception in template) falls back to the
    auto-generated line — templates should never break delivery."""
    tpl = (template or "").strip()
    if not tpl:
        return fallback
    try:
        return _jinja.from_string(tpl).render(**ctx)
    except Exception:
        return fallback


_MODULE = "ec2.host"

# Minimum sample count required before any rule can fire. Prevents a
# brand-new rule firing off a single tick.
_MIN_SAMPLES_TO_EVAL = 2

# Hard cap on samples kept per rule — defensive against pathological
# misconfig (window_seconds=86400 with 1s ticks would otherwise grow
# unboundedly). At 60s heartbeat × 30min window = 30 samples typical.
_MAX_SAMPLES_PER_RULE = 200


def evaluate(event: Event) -> list[Event]:
    """Hook point — called from hosts/projection.py for every heartbeat.
    Returns any synthetic host.perf.alert events that just fired."""
    if event.source.module != _MODULE or event.action != "host.service.health":
        return []
    instance_id = event.target.id or event.extra.get("instance_id")
    if not instance_id:
        return []

    extra = event.extra or {}
    tags = extra.get("tags") if isinstance(extra.get("tags"), dict) else {}
    tags = tags or {}

    metrics = _extract_metrics(extra)
    if not metrics:
        return []

    try:
        rules = storage.list_enabled_perf_rules_for_module(_MODULE)
    except Exception:
        # Never let a DB hiccup take down the projection — just skip this tick.
        return []

    now_ts = (event.event_time or datetime.now(timezone.utc)).timestamp()
    derived: list[Event] = []

    for rule in rules:
        if not _rule_targets_instance(rule, instance_id, tags):
            continue
        metric_value = metrics.get(rule["metric"])
        if metric_value is None:
            continue
        # Per-host evaluation — the samples buffer holds tuples from every
        # host that matches the rule's scope; breach ratio is computed against
        # only the current host's slice. See docstring on _evaluate_one for
        # why this matters (fleet-wide rules were previously diluted by quiet
        # hosts and missed real single-host spikes).
        fired = _evaluate_one(rule, metric_value, now_ts, instance_id)
        if fired:
            alert = _make_alert_event(event, instance_id, rule, metric_value)
            derived.append(alert)
            _dispatch_to_channels(alert, rule)

    return derived


# --- scope matching ---------------------------------------------------------


def _rule_targets_instance(rule: dict, instance_id: str, tags: dict) -> bool:
    """Match the heartbeat's instance against the rule's scope.

    Precedence (see sql/030_perf_alert_multi_instance.sql):
      1. instance_ids non-empty  → hit if instance_id ∈ list  (multi-instance)
      2. instance_id set          → exact match               (single-instance)
      3. tag_key + tag_value      → tag match                 (fleet by tag)
      4. everything else falsy    → matches every host        (all-scope)
    """
    ids = rule.get("instance_ids") or []
    if ids:
        return instance_id in ids
    if rule.get("instance_id"):
        return rule["instance_id"] == instance_id
    tk, tv = rule.get("tag_key"), rule.get("tag_value")
    if tk and tv is not None:
        return tags.get(tk) == tv
    # No scope set at all → all-instance rule (explicit opt-in via the API,
    # which allows all four fields to be empty only when scope=all).
    return True


# --- metric extraction ------------------------------------------------------


def _extract_metrics(extra: dict) -> dict[str, float]:
    """Pull numeric metrics from the heartbeat. Each metric is normalized
    to a percentage (0-100) so the user sets thresholds in the same units."""
    out: dict[str, float] = {}

    mem = extra.get("memory")
    if isinstance(mem, dict):
        v = mem.get("used_pct")
        if v is not None:
            try:
                out["memory_pct"] = float(v)
            except (TypeError, ValueError):
                pass

    cpu = extra.get("cpu")
    if isinstance(cpu, dict):
        # True CPU utilization (0-100%) computed from /proc/stat delta in
        # the agent. Matches CloudWatch's CPUUtilization.
        util = cpu.get("utilization_pct")
        if util is not None:
            try:
                out["cpu_utilization_pct"] = float(util)
            except (TypeError, ValueError):
                pass

    disk = extra.get("disk")
    if isinstance(disk, list) and disk:
        try:
            worst = max(
                float(d.get("used_pct") or 0)
                for d in disk
                if isinstance(d, dict) and d.get("used_pct") is not None
            )
            out["disk_pct_max"] = worst
        except (TypeError, ValueError):
            pass

    return out


# --- per-rule evaluator -----------------------------------------------------


def _evaluate_one(
    rule: dict, current_value: float, now_ts: float, instance_id: str,
) -> bool:
    """Returns True if the rule fires THIS tick for `instance_id`. Always
    persists state.

    Per-host semantics: the samples buffer contains tuples from every host
    that matches the rule's scope (relevant for tag-wide and all-hosts rules
    where multiple hosts share the same buffer). Each sample is tagged with
    `h` = the reporting instance_id. Breach ratio is computed against the
    slice of the buffer for the CURRENT host only — that way a fleet-wide
    rule fires when ANY single host has enough breach samples, instead of
    getting averaged into inactivity by quiet neighbours.

    Backward-compat: pre-fix samples missing `h` are treated as belonging to
    the current host (safe default — they age out of the window naturally).
    """
    breached = _compare(current_value, rule["threshold"], rule["comparison"])
    samples = list(rule.get("samples") or [])
    samples.append({
        "t": now_ts, "b": bool(breached), "v": current_value, "h": instance_id,
    })

    cutoff = now_ts - max(60, int(rule["window_seconds"]))
    samples = [s for s in samples if float(s.get("t", 0)) >= cutoff]

    # Defensive cap — see _MAX_SAMPLES_PER_RULE comment. Applies to the WHOLE
    # buffer (all hosts) so a very chatty fleet can't unboundedly grow one
    # rule row. Per-host ratio is computed after this cap.
    if len(samples) > _MAX_SAMPLES_PER_RULE:
        samples = samples[-_MAX_SAMPLES_PER_RULE:]

    # This-host slice of the buffer. Missing `h` (legacy sample) → assume
    # current host so old data doesn't spuriously block a fresh fire.
    host_samples = [
        s for s in samples
        if str(s.get("h", instance_id)) == instance_id
    ]

    # Decide whether to fire BEFORE persisting state — last_fired_at must
    # only update on actual fire.
    fire = False
    if len(host_samples) >= _MIN_SAMPLES_TO_EVAL:
        breach_count = sum(1 for s in host_samples if s.get("b"))
        ratio = breach_count / len(host_samples)
        if ratio >= float(rule["min_breach_ratio"]):
            # Throttle check.
            last_fired = rule.get("last_fired_at")
            if last_fired is None:
                fire = True
            else:
                last_fired_ts = (
                    last_fired.timestamp() if isinstance(last_fired, datetime)
                    else float(last_fired)
                )
                if (now_ts - last_fired_ts) >= int(rule["throttle_seconds"]):
                    fire = True

    fired_at = (
        datetime.fromtimestamp(now_ts, tz=timezone.utc) if fire else None
    )
    try:
        storage.update_perf_rule_state(
            rule["id"],
            samples=samples,
            last_value=current_value,
            last_fired_at=fired_at,
        )
    except Exception:
        # State persistence failure is not catastrophic — we lose this
        # rule's history for a tick. Better to keep serving heartbeats.
        pass

    return fire


def _compare(value: float, threshold: float, op: str) -> bool:
    if op == "gte":
        return value >= threshold
    if op == "gt":
        return value > threshold
    if op == "lte":
        return value <= threshold
    if op == "lt":
        return value < threshold
    return False


# --- alert event construction -----------------------------------------------


def _make_alert_event(
    heartbeat: Event,
    instance_id: str,
    rule: dict,
    current_value: float,
) -> Event:
    """Build the synthetic host.perf.alert event. Severity comes from the
    rule. `extra.actor=None` — these aren't tied to a person."""
    minutes = max(1, int(rule["window_seconds"] // 60))
    auto_msg = (
        f"{_metric_label(rule['metric'])} "
        f"{_op_symbol(rule['comparison'])} {_format_threshold(rule['threshold'])}% "
        f"for {minutes}m (current: {current_value:.1f}%)"
    )
    tags_map = (heartbeat.extra or {}).get("tags") or {}
    # Resolve display: user-set display_name > DNS hostname > instance_id.
    # Reading from storage is cheap (one row lookup) and only happens when a
    # perf alert actually fires, so it stays off the heartbeat hot path.
    display = None
    try:
        row = storage.get_host_status(instance_id)
        if row:
            display = row.get("display_name")
    except Exception:
        display = None
    heartbeat_host = (heartbeat.target.name if heartbeat.target else None)
    resolved_hostname = display or heartbeat_host or instance_id

    # Timestamp bundle for the template — lets operators eyeball the delay
    # between the metric being observed (window_end) and when Slack/etc.
    # actually shows the message. window_start / window_end are minute-
    # precision because the observation window is defined in whole minutes.
    fired_dt = heartbeat.event_time or datetime.now(timezone.utc)
    if fired_dt.tzinfo is None:
        fired_dt = fired_dt.replace(tzinfo=timezone.utc)
    window_end_dt = fired_dt.replace(second=0, microsecond=0)
    from datetime import timedelta as _td
    window_start_dt = window_end_dt - _td(minutes=minutes)
    fired_at_str = fired_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    window_start_str = window_start_dt.strftime("%Y-%m-%d %H:%M UTC")
    window_end_str = window_end_dt.strftime("%Y-%m-%d %H:%M UTC")
    # Compact same-day form for one-line templates: "14:27–14:32 UTC".
    window_range_str = (
        f"{window_start_dt.strftime('%H:%M')}"
        f"–{window_end_dt.strftime('%H:%M')} UTC"
    )
    msg = _render_message(
        rule.get("message_template"),
        auto_msg,
        {
            "instance_id": instance_id,
            "hostname": resolved_hostname,
            "display_name": display,
            "metric": rule["metric"],
            "metric_label": _metric_label(rule["metric"]),
            "threshold": rule["threshold"],
            "comparison": rule["comparison"],
            "current_value": current_value,
            "window_seconds": rule["window_seconds"],
            "window_minutes": minutes,
            "rule_name": rule["name"],
            "severity": rule["severity"],
            # Timestamp bundle — all UTC; format is stable so grep still works.
            "fired_at": fired_at_str,
            "window_start": window_start_str,
            "window_end": window_end_str,
            "window_range": window_range_str,
            "event_time": fired_dt.isoformat(),
            "tags": tags_map,
        },
    )
    # Rebuild the event's target with the resolved friendly name so channel
    # templates that reference `event.target.name` render "Prod-NAT" instead
    # of "ip-172-16-1-97.us-west-1.compute.internal" or the raw instance id.
    # Keep the original target's other fields; only `name` gets promoted.
    from .event import Target as _Target
    friendly_target = _Target(
        id=(heartbeat.target.id if heartbeat.target else instance_id),
        type=(heartbeat.target.type if heartbeat.target else "ec2.instance"),
        name=resolved_hostname,
    )
    return Event(
        source=heartbeat.source,
        event_time=heartbeat.event_time,
        category=Category.host,
        action="host.perf.alert",
        outcome=Outcome.failure,
        target=friendly_target,
        severity=rule["severity"],
        extra={
            "instance_id": instance_id,
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "display_name": display,
            "hostname": resolved_hostname,
            "metric": rule["metric"],
            "metric_label": _metric_label(rule["metric"]),
            "threshold": float(rule["threshold"]),
            "comparison": rule["comparison"],
            "current_value": float(current_value),
            "window_seconds": int(rule["window_seconds"]),
            "min_breach_ratio": float(rule["min_breach_ratio"]),
            "message": msg,
            # propagate the tags from the heartbeat so notification templates
            # can reference env/role like other host events.
            "tags": (heartbeat.extra or {}).get("tags") or {},
        },
        raw={
            "kind": "perf_alert",
            "metric": rule["metric"],
            "value": current_value,
            "threshold": rule["threshold"],
        },
    )


def _metric_label(metric: str) -> str:
    return {
        "memory_pct": "Memory",
        "cpu_utilization_pct": "CPU utilization",
        "disk_pct_max": "Disk (worst mount)",
    }.get(metric, metric)


def _op_symbol(op: str) -> str:
    return {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<"}.get(op, "?")


def _format_threshold(t: Any) -> str:
    # Trim trailing .0 for whole numbers — `80%` reads better than `80.0%`.
    try:
        f = float(t)
        return f"{int(f)}" if f.is_integer() else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(t)


# --- channel dispatch -------------------------------------------------------


def _dispatch_to_channels(event: Event, rule: dict) -> None:
    """Hand the alert to the notifier's direct-dispatch path. Channel
    list lives on the rule itself — the operator picked it at rule
    creation so we don't need to match notification rules separately."""
    channels = rule.get("channels") or []
    if not channels:
        return
    try:
        from .notify.router import get_notifier
        notifier = get_notifier()
        notifier.dispatch_direct(
            event,
            channel_names=list(channels),
            rule_name=rule["name"],
            rule_id=rule["id"],
            throttle_seconds=int(rule["throttle_seconds"]),
        )
    except Exception:
        # Don't let dispatch failure break the projection — the event still
        # got emitted; operators can see it in /events even if Slack/Email
        # didn't go out.
        pass
