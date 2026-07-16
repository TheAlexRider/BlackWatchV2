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
        fired = _evaluate_one(rule, metric_value, now_ts)
        if fired:
            alert = _make_alert_event(event, instance_id, rule, metric_value)
            derived.append(alert)
            _dispatch_to_channels(alert, rule)

    return derived


# --- scope matching ---------------------------------------------------------


def _rule_targets_instance(rule: dict, instance_id: str, tags: dict) -> bool:
    if rule.get("instance_id") and rule["instance_id"] == instance_id:
        return True
    tk, tv = rule.get("tag_key"), rule.get("tag_value")
    if tk and tv is not None and tags.get(tk) == tv:
        return True
    return False


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
        load_norm = cpu.get("load_norm")
        if load_norm is None:
            try:
                lo = float(cpu.get("load_1min") or 0)
                n = max(1.0, float(cpu.get("cpu_count") or 1))
                load_norm = lo / n
            except (TypeError, ValueError):
                load_norm = None
        if load_norm is not None:
            try:
                # Represent as percentage: load_norm 1.0 = "100% busy".
                out["cpu_load_norm"] = float(load_norm) * 100.0
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


def _evaluate_one(rule: dict, current_value: float, now_ts: float) -> bool:
    """Returns True if the rule fires THIS tick. Always persists state."""
    breached = _compare(current_value, rule["threshold"], rule["comparison"])
    samples = list(rule.get("samples") or [])
    samples.append({"t": now_ts, "b": bool(breached), "v": current_value})

    cutoff = now_ts - max(60, int(rule["window_seconds"]))
    samples = [s for s in samples if float(s.get("t", 0)) >= cutoff]

    # Defensive cap — see _MAX_SAMPLES_PER_RULE comment.
    if len(samples) > _MAX_SAMPLES_PER_RULE:
        samples = samples[-_MAX_SAMPLES_PER_RULE:]

    # Decide whether to fire BEFORE persisting state — last_fired_at must
    # only update on actual fire.
    fire = False
    if len(samples) >= _MIN_SAMPLES_TO_EVAL:
        breach_count = sum(1 for s in samples if s.get("b"))
        ratio = breach_count / len(samples)
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
    msg = _render_message(
        rule.get("message_template"),
        auto_msg,
        {
            "instance_id": instance_id,
            "hostname": (heartbeat.target.name if heartbeat.target else None) or instance_id,
            "metric": rule["metric"],
            "metric_label": _metric_label(rule["metric"]),
            "threshold": rule["threshold"],
            "comparison": rule["comparison"],
            "current_value": current_value,
            "window_seconds": rule["window_seconds"],
            "window_minutes": minutes,
            "rule_name": rule["name"],
            "severity": rule["severity"],
            "tags": tags_map,
        },
    )
    return Event(
        source=heartbeat.source,
        event_time=heartbeat.event_time,
        category=Category.host,
        action="host.perf.alert",
        outcome=Outcome.failure,
        target=heartbeat.target,
        severity=rule["severity"],
        extra={
            "instance_id": instance_id,
            "rule_id": rule["id"],
            "rule_name": rule["name"],
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
        "cpu_load_norm": "CPU (normalized load)",
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
