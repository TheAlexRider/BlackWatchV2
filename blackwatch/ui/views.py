"""Built-in operational console — server-rendered HTML, no SPA, no build step.
Read-only views over the same data the API exposes. Lives in the app so there
is one system, not a separate dashboard tool."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import noise, storage
from ..connectors import runner as connector_runner
from ..connectors.models import (
    AwsCloudtrailSqsConfig, AwsEcsHealthConfig,
    AwsPostureDriftConfig, AwsS3AccessLogsConfig, AwsS3DriftConfig,
    CertProbeConfig,
)
from ..notify import router as notify_router
from ..notify.model import NotificationRule
from ..rules import engine as rule_engine
from ..rules.model import Condition

router = APIRouter()
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_SEVERITY_ORDER = ["critical", "high", "medium", "low", "informational", "unscored"]
_STALE_AFTER = 180


def _fmt_ts(value: Any) -> Any:
    """Render a timestamp as a `<time>` element carrying its canonical UTC value
    in `datetime=`, with the visible text defaulting to UTC. A tiny script in
    base.html re-formats the visible text on the client side based on the user's
    selected timezone (UTC / PST / PDT / IST) — no server roundtrip needed."""
    from datetime import datetime, timezone

    from markupsafe import Markup, escape

    if not value:
        return "-"

    # Coerce whatever storage handed us (datetime, ISO string, …) into a UTC datetime.
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value)
        try:
            # Handles "2026-06-02T03:21:45+00:00", "...Z", "...+00:00", and the
            # plain "2026-06-02 03:21:45" Postgres style (Python 3.11+).
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            # Unknown shape — degrade gracefully to the old truncated display
            # but still mark it as UTC so the user knows what they're looking at.
            return Markup(f"{escape(s.replace('T', ' ')[:19])} UTC")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    iso = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    display = utc.strftime("%Y-%m-%d %H:%M:%S")
    return Markup(f'<time class="ts" datetime="{iso}">{display} UTC</time>')


_TEMPLATES.env.filters["ts"] = _fmt_ts


def _vpn_view() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    servers = []
    for row in storage.list_vpn_status():
        clients = row["clients"] or []
        age = (now - row["updated_at"]).total_seconds()
        servers.append(
            {
                "server": row["server"],
                "active": row["active"],
                "clients": clients,
                "client_count": len(clients),
                "age": int(age),
                "stale": age > _STALE_AFTER,
                "updated_at": row["updated_at"].isoformat(),
            }
        )
    return servers


@router.get("/ui", response_class=HTMLResponse)
def dashboard(request: Request) -> Any:
    counts = storage.severity_counts()
    ordered = [(sev, counts.get(sev, 0)) for sev in _SEVERITY_ORDER]
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    return _TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "counts": ordered,
            "total": sum(counts.values()),
            "notable": storage.query_events(severities=["high", "critical"], limit=10),
            "recent": storage.query_events(limit=15),
            "vpn": _vpn_view(),
            "volume_24h": storage.event_count_since(since_24h),
            "volume_7d": storage.event_count_since(now - timedelta(days=7)),
            "top_actions": storage.action_counts(since_24h, limit=12),
        },
    )


@router.get("/ui/events", response_class=HTMLResponse)
def events(
    request: Request,
    category: str | None = None,
    severity: str | None = None,
    module: str | None = None,
    action: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> Any:
    results = storage.query_events(
        category=category or None,
        severity=severity or None,
        module=module or None,
        action=action or None,
        q=q or None,
        limit=limit,
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "events.html",
        {
            "events": results,
            "filters": {
                "category": category or "",
                "severity": severity or "",
                "module": module or "",
                "action": action or "",
                "q": q or "",
            },
            "severity_order": _SEVERITY_ORDER,
        },
    )


@router.get("/ui/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: str) -> Any:
    event = storage.get_event(event_id)
    raw = event.pop("raw", None) if event else None
    return _TEMPLATES.TemplateResponse(
        request,
        "event_detail.html",
        {
            "event_id": event_id,
            "event": event,
            "envelope_json": json.dumps(event, indent=2, default=str) if event else None,
            "raw_json": json.dumps(raw, indent=2, default=str) if raw is not None else None,
        },
    )


@router.get("/ui/vpn", response_class=HTMLResponse)
def vpn(request: Request) -> Any:
    recent_vpn = storage.query_events(category="vpn", limit=300)
    auth = [
        e for e in recent_vpn
        if e.get("action") in ("vpn.auth.success", "vpn.auth.failure")
    ][:40]
    return _TEMPLATES.TemplateResponse(
        request, "vpn.html", {"servers": _vpn_view(), "auth": auth}
    )


@router.get("/ui/hosts/{instance_id}", response_class=HTMLResponse)
def host_detail(request: Request, instance_id: str) -> Any:
    host = storage.get_host_status(instance_id)
    now = datetime.now(timezone.utc)
    age: int | None = None
    stale = False
    if host and host.get("updated_at"):
        age = int((now - host["updated_at"]).total_seconds())
        stale = age > 180
    snapshots = (host.get("snapshots") if host else None) or {}
    recent = storage.query_events(target_id=instance_id, limit=150)
    change_prefixes = (
        "host.port.", "host.user.", "host.authorized_key.", "host.sudoers.",
        "host.file.", "host.cron.", "host.service.", "host.suid.", "host.packages.",
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "host_detail.html",
        {
            "host": host, "instance_id": instance_id,
            "snapshots": snapshots, "age": age, "stale": stale,
            "auth_events": [e for e in recent
                            if e.get("action", "").startswith(("host.auth", "host.sudo"))][:30],
            "state_changes": [e for e in recent
                              if e.get("action", "").startswith(change_prefixes)][:30],
            "alerts": [e for e in recent
                       if e.get("severity") in ("high", "critical")][:20],
        },
    )


@router.get("/ui/hosts", response_class=HTMLResponse)
def hosts(request: Request) -> Any:
    now = datetime.now(timezone.utc)
    servers = []
    for row in storage.list_host_status():
        age = (now - row["updated_at"]).total_seconds() if row["updated_at"] else None
        snaps = row.get("snapshots") or {}
        servers.append(
            {
                "instance_id": row["instance_id"],
                "hostname": row["hostname"],
                "account": row["account"],
                "region": row["region"],
                "active": row["active"],
                "age_seconds": int(age) if age is not None else None,
                "stale": age is not None and age > 180,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "-",
                "port_count": len(snaps.get("ports") or []),
                "user_count": len(snaps.get("users") or []),
                "key_count": len(snaps.get("authorized_keys") or []),
            }
        )
    recent = storage.query_events(category="host", limit=200)
    auth = [e for e in recent if e.get("action", "").startswith(("host.auth", "host.sudo"))][:40]
    change_prefixes = (
        "host.port.", "host.user.", "host.authorized_key.", "host.sudoers.",
        "host.file.", "host.cron.", "host.service.", "host.suid.", "host.packages.",
    )
    changes = [e for e in recent if e.get("action", "").startswith(change_prefixes)][:40]
    return _TEMPLATES.TemplateResponse(
        request, "hosts.html", {"servers": servers, "auth": auth, "changes": changes}
    )


@router.get("/ui/rules", response_class=HTMLResponse)
def rules(request: Request, msg: str | None = None) -> Any:
    # Legacy Jinja page — kept working for anyone with a bookmark. The
    # `muted` list here is intentionally the simple action-only view
    # (the old template can't render the new filter columns anyway).
    return _TEMPLATES.TemplateResponse(
        request,
        "rules.html",
        {
            "rules": rule_engine.get_engine().rules,
            "muted": [m["action"] for m in storage.list_muted_events()],
            "msg": msg,
        },
    )


def _rules_redirect(message: str = "") -> RedirectResponse:
    url = "/ui/rules" + (f"?msg={message}" if message else "")
    return RedirectResponse(url=url, status_code=303)


@router.post("/ui/rules/{rule_id}/toggle")
def rule_toggle(rule_id: str, enabled: str = Form("")) -> RedirectResponse:
    on = enabled == "on"
    storage.set_rule_override(rule_id, on)
    rule_engine.get_engine().set_enabled(rule_id, on)
    return _rules_redirect(f"{rule_id} {'enabled' if on else 'disabled'}")


@router.post("/ui/mute")
def mute_action(action: str = Form(...)) -> RedirectResponse:
    """Legacy no-filter mute. New UI at /rules supports contextual filters
    (source_type / username / reason). Left here for backwards compat."""
    action = action.strip()
    if action:
        storage.add_muted_event(action)
        noise.refresh()
    return _rules_redirect(f"muting {action}")


@router.post("/ui/unmute")
def unmute_action(action: str = Form(...)) -> RedirectResponse:
    """Legacy unmute-by-action-string. Drops every mute rule whose action
    matches (the old data model had at most one per action)."""
    action = action.strip()
    for m in storage.list_muted_events():
        if m["action"] == action:
            storage.remove_muted_event(int(m["id"]))
    noise.refresh()
    return _rules_redirect(f"unmuted {action}")


# --- Notifications: rules (Phase 1) -----------------------------------------

def _notif_redirect(message: str = "") -> RedirectResponse:
    url = "/ui/notifications/rules" + (f"?msg={message}" if message else "")
    return RedirectResponse(url=url, status_code=303)


def _default_match_yaml() -> str:
    return "field: severity\nop: in\nvalue: [high, critical]\n"


@router.get("/ui/notifications/rules", response_class=HTMLResponse)
def notification_rules_page(
    request: Request, edit: str | None = None, msg: str | None = None
) -> Any:
    notifier = notify_router.get_notifier()
    notifier.reload_rules()  # always fresh on view
    rules_view = []
    now = datetime.now(timezone.utc)
    for r in notifier.rules:
        silenced = r.silence_until is not None and r.silence_until > now
        rules_view.append({
            "id": r.id, "name": r.name, "enabled": r.enabled,
            "channels": r.channels, "throttle_seconds": r.throttle_seconds,
            "silence_until": r.silence_until.isoformat() if r.silence_until else None,
            "silenced": silenced,
            "match_yaml": yaml.safe_dump(r.match.model_dump(exclude_none=True, by_alias=True),
                                         default_flow_style=False, sort_keys=False).strip(),
        })
    editing = next((r for r in rules_view if r["id"] == edit), None) if edit else None
    return _TEMPLATES.TemplateResponse(
        request,
        "notifications_rules.html",
        {
            "rules": rules_view,
            "editing": editing,
            "all_channels": sorted(notifier.channels.keys()),
            "default_match_yaml": _default_match_yaml(),
            "msg": msg,
        },
    )


@router.post("/ui/notifications/rules/save")
def notification_rule_save(
    rule_id: str = Form(""),
    name: str = Form(...),
    enabled: str = Form(""),
    match_yaml: str = Form(""),
    channels: list[str] = Form(default_factory=list),
    throttle_seconds: int = Form(0),
) -> RedirectResponse:
    try:
        match_dict = yaml.safe_load(match_yaml) or {}
        if not isinstance(match_dict, dict):
            raise ValueError("match must be a YAML mapping")
        Condition(**match_dict)  # validate against the Condition schema
    except Exception as exc:
        return _notif_redirect(f"invalid match: {exc}")
    rid = rule_id or str(uuid.uuid4())
    storage.upsert_notification_rule(
        rule_id=rid, name=name, enabled=(enabled == "on"),
        match=match_dict, channels=channels, throttle_seconds=throttle_seconds,
    )
    notify_router.get_notifier().reload_rules()
    return _notif_redirect(f"saved {name}")


@router.post("/ui/notifications/rules/{rule_id}/toggle")
def notification_rule_toggle(rule_id: str, enabled: str = Form("")) -> RedirectResponse:
    storage.set_notification_rule_enabled(rule_id, enabled == "on")
    notify_router.get_notifier().reload_rules()
    return _notif_redirect("toggled")


@router.post("/ui/notifications/rules/{rule_id}/silence")
def notification_rule_silence(rule_id: str, hours: int = Form(0)) -> RedirectResponse:
    if hours <= 0:
        storage.set_notification_rule_silence(rule_id, None)
        msg = "silence cleared"
    else:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        storage.set_notification_rule_silence(rule_id, until)
        msg = f"silenced for {hours}h"
    notify_router.get_notifier().reload_rules()
    return _notif_redirect(msg)


@router.post("/ui/notifications/rules/{rule_id}/test")
def notification_rule_test(rule_id: str) -> RedirectResponse:
    results = notify_router.get_notifier().test_rule(rule_id)
    sent = sum(1 for r in results if r.get("status") == "sent")
    errors = [r for r in results if r.get("status") not in ("sent", "unknown_rule")]
    if sent and not errors:
        return _notif_redirect(f"test ok ({sent} channel(s))")
    return _notif_redirect(f"test: {results}")


@router.post("/ui/notifications/rules/{rule_id}/delete")
def notification_rule_delete(rule_id: str) -> RedirectResponse:
    storage.delete_notification_rule(rule_id)
    notify_router.get_notifier().reload_rules()
    return _notif_redirect("rule deleted")


# --- Notifications: channels (Phase 2) ---------------------------------------

_CHANNEL_TYPES = ("slack", "webhook", "email", "pagerduty", "teams", "discord")


def _channels_redirect(message: str = "") -> RedirectResponse:
    url = "/ui/notifications/channels" + (f"?msg={message}" if message else "")
    return RedirectResponse(url=url, status_code=303)


def _default_config_yaml(ctype: str) -> str:
    examples = {
        "slack": "url: https://hooks.slack.com/services/REPLACE/ME\n",
        "webhook": "url: http://host.docker.internal:9000/hook\n",
        "teams": "url: https://outlook.office.com/webhook/REPLACE\n",
        "discord": "url: https://discord.com/api/webhooks/REPLACE\n",
        "email": ("smtp_host: smtp.gmail.com\n"
                  "smtp_port: 587\n"
                  "use_tls: true\n"
                  "smtp_user: alerts@example.com\n"
                  "password_env: SMTP_PASS    # name of env var holding the password\n"
                  "from_addr: alerts@example.com\n"
                  "to_addrs: [you@example.com]\n"),
        "pagerduty": "routing_key_env: PD_ROUTING_KEY   # name of env var holding the key\n",
    }
    return examples.get(ctype, "")


@router.get("/ui/notifications/channels", response_class=HTMLResponse)
def notification_channels_page(
    request: Request, edit: str | None = None, msg: str | None = None
) -> Any:
    rows = storage.list_notification_channels()
    editing = next((c for c in rows if c["id"] == edit), None) if edit else None
    if editing is not None:
        editing["config_yaml"] = yaml.safe_dump(editing.get("config") or {},
                                                default_flow_style=False, sort_keys=False).strip()
    return _TEMPLATES.TemplateResponse(
        request,
        "notifications_channels.html",
        {
            "channels": rows, "editing": editing,
            "channel_types": _CHANNEL_TYPES,
            "default_config_yaml": _default_config_yaml(
                editing["type"] if editing else "slack"),
            "msg": msg,
        },
    )


@router.post("/ui/notifications/channels/save")
def notification_channel_save(
    channel_id: str = Form(""),
    name: str = Form(...),
    type: str = Form(...),
    enabled: str = Form(""),
    config_yaml: str = Form(""),
    message_template: str = Form(""),
    retries: int = Form(3),
    retry_backoff_seconds: int = Form(5),
    rate_limit_per_min: int = Form(0),
    dedup_window_seconds: int = Form(300),
    digest_window_seconds: int = Form(0),
) -> RedirectResponse:
    if type not in _CHANNEL_TYPES:
        return _channels_redirect(f"unknown type: {type}")
    try:
        config = yaml.safe_load(config_yaml) or {}
        if not isinstance(config, dict):
            raise ValueError("config must be a YAML mapping")
    except Exception as exc:
        return _channels_redirect(f"invalid config: {exc}")
    cid = channel_id or str(uuid.uuid4())
    storage.upsert_notification_channel(
        channel_id=cid, name=name, ctype=type, enabled=(enabled == "on"),
        config=config, message_template=(message_template.strip() or None),
        retries=retries, retry_backoff_seconds=retry_backoff_seconds,
        rate_limit_per_min=rate_limit_per_min,
        dedup_window_seconds=dedup_window_seconds,
        digest_window_seconds=digest_window_seconds,
    )
    notify_router.get_notifier().reload_channels()
    return _channels_redirect(f"saved {name}")


@router.post("/ui/notifications/channels/{channel_id}/toggle")
def notification_channel_toggle(channel_id: str, enabled: str = Form("")) -> RedirectResponse:
    storage.set_notification_channel_enabled(channel_id, enabled == "on")
    notify_router.get_notifier().reload_channels()
    return _channels_redirect("toggled")


@router.post("/ui/notifications/channels/{channel_id}/test")
def notification_channel_test(channel_id: str) -> RedirectResponse:
    row = storage.get_notification_channel(channel_id)
    if row is None:
        return _channels_redirect("channel not found")
    result = notify_router.get_notifier().send_test(row["name"])
    return _channels_redirect(f"test {result.get('status')}: {result.get('detail', '')}")


@router.post("/ui/notifications/channels/{channel_id}/delete")
def notification_channel_delete(channel_id: str) -> RedirectResponse:
    storage.delete_notification_channel(channel_id)
    notify_router.get_notifier().reload_channels()
    return _channels_redirect("deleted")


# --- Notifications: log + acks (Phase 2) -------------------------------------

@router.get("/ui/notifications/log", response_class=HTMLResponse)
def notification_log_page(
    request: Request, status: str | None = None, channel: str | None = None,
    rule: str | None = None,
) -> Any:
    entries = storage.list_notification_log(
        status=status or None, channel_name=channel or None,
        rule_name=rule or None, limit=300,
    )
    return _TEMPLATES.TemplateResponse(
        request, "notifications_log.html",
        {"entries": entries, "filters": {"status": status or "",
                                          "channel": channel or "", "rule": rule or ""}},
    )


@router.get("/ui/notifications/acks", response_class=HTMLResponse)
def notification_acks_page(request: Request, msg: str | None = None) -> Any:
    acks = storage.list_notification_acks()
    return _TEMPLATES.TemplateResponse(
        request, "notifications_acks.html", {"acks": acks, "msg": msg},
    )


@router.post("/ui/notifications/ack")
def notification_ack(
    fingerprint: str = Form(...),
    hours: int = Form(4),
    reason: str = Form(""),
    back_to: str = Form("/ui/notifications/acks"),
) -> RedirectResponse:
    if hours <= 0:
        storage.remove_notification_ack(fingerprint.strip())
    else:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        storage.add_notification_ack(fingerprint.strip(), until, reason.strip() or None)
    return RedirectResponse(url=back_to, status_code=303)


# --- Settings / Connectors ----------------------------------------------------

def _settings_redirect(message: str = "") -> RedirectResponse:
    url = "/ui/settings" + (f"?msg={message}" if message else "")
    return RedirectResponse(url=url, status_code=303)


@router.get("/ui/settings", response_class=HTMLResponse)
def settings_page(request: Request, edit: str | None = None, msg: str | None = None) -> Any:
    connectors = storage.list_connectors()
    editing = next((c for c in connectors if c["id"] == edit), None) if edit else None
    return _TEMPLATES.TemplateResponse(
        request,
        "settings.html",
        {"connectors": connectors, "editing": editing, "msg": msg},
    )


@router.post("/ui/connectors/save_aws")
def connector_save_aws(
    connector_id: str = Form(""),
    name: str = Form(...),
    queue_url: str = Form(...),
    aws_region: str = Form("us-east-1"),
    aws_profile: str = Form(""),
    target_module: str = Form("aws.cloudtrail"),
    interval_seconds: int = Form(60),
) -> RedirectResponse:
    config = AwsCloudtrailSqsConfig(
        queue_url=queue_url,
        aws_region=aws_region,
        aws_profile=aws_profile or None,
        target_module=target_module,
        interval_seconds=interval_seconds,
    ).model_dump()
    cid = connector_id or str(uuid.uuid4())
    storage.upsert_connector(cid, name, "aws_cloudtrail_sqs", config)
    return _settings_redirect("saved (test to verify, then enable)")


@router.post("/ui/connectors/save_aws_ecs")
def connector_save_aws_ecs(
    connector_id: str = Form(""),
    name: str = Form(...),
    vpc: str = Form(...),
    aws_region: str = Form("us-west-1"),
    aws_profile: str = Form("blackwatch"),
    interval_seconds: int = Form(60),
    running_smoothing_minutes: int = Form(5),
) -> RedirectResponse:
    config = AwsEcsHealthConfig(
        vpc=vpc,
        aws_region=aws_region,
        aws_profile=aws_profile or None,
        interval_seconds=interval_seconds,
        running_smoothing_minutes=running_smoothing_minutes,
    ).model_dump()
    cid = connector_id or str(uuid.uuid4())
    storage.upsert_connector(cid, name, "aws_ecs_health", config)
    return _settings_redirect("saved (test to verify, then enable)")


# ---------- ECS services / probe targets pages ------------------------------

def _service_status_view(stale_after: int = 180) -> list[dict[str, Any]]:
    """One row per known probe_target with its current status. Joins targets
    (config / severity / tags) with service_status (current status, last_seen)."""
    now = datetime.now(timezone.utc)
    targets = {t["id"]: t for t in storage.list_probe_targets()}
    statuses = {s["target_id"]: s for s in storage.list_service_status()}
    out: list[dict[str, Any]] = []
    for tid, t in targets.items():
        s = statuses.get(tid)
        if s and s.get("last_seen"):
            age = int((now - s["last_seen"]).total_seconds())
            stale = age > stale_after
        else:
            age = None
            stale = True
        out.append({
            **t,
            "status": (s or {}).get("status") or "unknown",
            "last_seen": (s or {}).get("last_seen"),
            "age_seconds": age,
            "stale": stale,
            "latency_ms": (s or {}).get("latency_ms"),
            "consecutive_fails": (s or {}).get("consecutive_fails") or 0,
        })
    out.sort(key=lambda x: (x["vpc"], x["name"]))
    return out


@router.get("/ui/services", response_class=HTMLResponse)
def services(request: Request, vpc: str | None = None) -> Any:
    rows = _service_status_view()
    if vpc:
        rows = [r for r in rows if r["vpc"] == vpc]
    vpcs = sorted({r["vpc"] for r in _service_status_view()})
    # Group by VPC for the page
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["vpc"], []).append(r)
    agents = storage.list_probe_agents()
    return _TEMPLATES.TemplateResponse(
        request, "services.html",
        {"grouped": grouped, "vpcs": vpcs, "selected_vpc": vpc, "agents": agents},
    )


@router.get("/ui/services/targets", response_class=HTMLResponse)
def services_targets(request: Request, edit: str | None = None, msg: str | None = None) -> Any:
    """One-at-a-time target management. The form is the primary thing; the
    table below it shows what you've created with live status so you can verify
    each addition before moving to the next."""
    targets = storage.list_probe_targets()
    # Join live status so the list shows up/down/etc next to each saved target.
    status_by_id = {s["target_id"]: s for s in storage.list_service_status()}
    now = datetime.now(timezone.utc)
    rows = []
    for t in targets:
        s = status_by_id.get(t["id"])
        if s and s.get("last_seen"):
            age = int((now - s["last_seen"]).total_seconds())
        else:
            age = None
        rows.append({
            **t,
            "status": (s or {}).get("status") or "unknown",
            "age_seconds": age,
            "latency_ms": (s or {}).get("latency_ms"),
        })
    editing = next((t for t in rows if t["id"] == edit), None) if edit else None
    return _TEMPLATES.TemplateResponse(
        request, "services_targets.html",
        {"targets": rows, "editing": editing, "msg": msg},
    )


def _targets_redirect(msg: str | None = None) -> RedirectResponse:
    return RedirectResponse(
        url=f"/ui/services/targets{('?msg=' + msg) if msg else ''}",
        status_code=303,
    )


@router.post("/ui/services/targets/save")
def services_target_save(
    target_id: str = Form(""),
    name: str = Form(...),
    vpc: str = Form(...),
    tier: str = Form(...),
    config_yaml: str = Form("{}"),
    severity_when_down: str = Form("high"),
    tags_yaml: str = Form("{}"),
    enabled: str = Form("on"),
) -> RedirectResponse:
    try:
        config = yaml.safe_load(config_yaml) or {}
        tags = yaml.safe_load(tags_yaml) or {}
    except yaml.YAMLError as exc:
        return _targets_redirect(f"yaml error: {exc}")
    if not isinstance(config, dict) or not isinstance(tags, dict):
        return _targets_redirect("config and tags must be YAML objects")
    if tier not in ("ecs_health", "ecs_running", "http_alive", "tcp"):
        return _targets_redirect(f"unknown tier: {tier}")
    tid = target_id or str(uuid.uuid4())
    storage.upsert_probe_target(
        tid, name=name, vpc=vpc, tier=tier, config=config,
        severity_when_down=severity_when_down, tags=tags,
        enabled=(enabled == "on"),
    )
    return _targets_redirect("saved")


@router.post("/ui/services/targets/save_bulk")
def services_target_save_bulk(targets_yaml: str = Form(...)) -> RedirectResponse:
    """Bulk import — paste a YAML list of targets. Each entry mirrors the
    single-target form. Existing targets with the same (name, vpc) are
    updated; others are created. This is the fast path for the initial 25-50
    services rollout."""
    try:
        data = yaml.safe_load(targets_yaml) or []
    except yaml.YAMLError as exc:
        return _targets_redirect(f"yaml error: {exc}")
    if not isinstance(data, list):
        return _targets_redirect("bulk import must be a YAML list")
    existing = {(t["name"], t["vpc"]): t for t in storage.list_probe_targets()}
    saved = 0
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name, vpc, tier = entry.get("name"), entry.get("vpc"), entry.get("tier")
        if not (name and vpc and tier):
            continue
        prev = existing.get((name, vpc))
        tid = prev["id"] if prev else str(uuid.uuid4())
        storage.upsert_probe_target(
            tid, name=name, vpc=vpc, tier=tier,
            config=entry.get("config") or {},
            severity_when_down=entry.get("severity_when_down") or "high",
            tags=entry.get("tags") or {},
            enabled=bool(entry.get("enabled", True)),
        )
        saved += 1
    return _targets_redirect(f"bulk saved {saved}")


@router.post("/ui/services/targets/{target_id}/delete")
def services_target_delete(target_id: str) -> RedirectResponse:
    storage.delete_probe_target(target_id)
    return _targets_redirect("deleted")


@router.post("/ui/services/targets/{target_id}/toggle")
def services_target_toggle(target_id: str, enabled: str = Form(...)) -> RedirectResponse:
    t = storage.get_probe_target(target_id)
    if not t:
        return _targets_redirect("not found")
    storage.upsert_probe_target(
        target_id, name=t["name"], vpc=t["vpc"], tier=t["tier"],
        config=t["config"], severity_when_down=t["severity_when_down"],
        tags=t["tags"], enabled=(enabled == "on"),
    )
    return _targets_redirect("toggled")


# ---------- S3 inventory page + drift connector save ------------------------

@router.get("/ui/buckets", response_class=HTMLResponse)
def buckets(request: Request) -> Any:
    rows = storage.list_bucket_status()
    public_count = sum(1 for b in rows if b.get("public"))
    unenc_count = sum(1 for b in rows if (b.get("encryption") or "none") == "none")
    no_versioning_count = sum(1 for b in rows
                              if (b.get("versioning") or "Disabled") != "Enabled")
    return _TEMPLATES.TemplateResponse(
        request, "buckets.html",
        {"buckets": rows, "public_count": public_count,
         "unenc_count": unenc_count, "no_versioning_count": no_versioning_count},
    )


@router.post("/ui/connectors/save_cert_probe")
def connector_save_cert_probe(
    connector_id: str = Form(""),
    name: str = Form(...),
    targets_raw: str = Form(""),
    interval_seconds: int = Form(3600),
    timeout_seconds: int = Form(5),
) -> RedirectResponse:
    """Targets are submitted as one-per-line in the textarea:
        name,host,port[,sni]
    Blank lines and lines starting with `#` are ignored.
    """
    targets: list[dict[str, Any]] = []
    for line in (targets_raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            return _settings_redirect(f"bad cert target line: {line!r}")
        target_name = parts[0]
        host = parts[1]
        port = int(parts[2]) if len(parts) >= 3 and parts[2] else 443
        sni = parts[3] if len(parts) >= 4 and parts[3] else None
        targets.append({"name": target_name, "host": host, "port": port, "sni": sni})
    config = CertProbeConfig(
        targets=targets,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
    ).model_dump()
    cid = connector_id or str(uuid.uuid4())
    storage.upsert_connector(cid, name, "cert_probe", config)
    return _settings_redirect("saved (test to verify, then enable)")


@router.post("/ui/connectors/save_aws_s3")
def connector_save_aws_s3(
    connector_id: str = Form(""),
    name: str = Form(...),
    aws_profile: str = Form("blackwatch"),
    interval_seconds: int = Form(3600),
) -> RedirectResponse:
    config = AwsS3DriftConfig(
        aws_profile=aws_profile or None,
        interval_seconds=interval_seconds,
    ).model_dump()
    cid = connector_id or str(uuid.uuid4())
    storage.upsert_connector(cid, name, "aws_s3_drift", config)
    return _settings_redirect("saved (test to verify, then enable)")


@router.post("/ui/connectors/save_aws_s3_access")
def connector_save_aws_s3_access(
    connector_id: str = Form(""),
    name: str = Form(...),
    bucket: str = Form(...),
    prefix: str = Form(""),
    aws_region: str = Form("us-west-1"),
    aws_profile: str = Form("blackwatch"),
    interval_seconds: int = Form(300),
    max_files_per_run: int = Form(200),
) -> RedirectResponse:
    config = AwsS3AccessLogsConfig(
        bucket=bucket.strip(),
        prefix=prefix.strip(),
        aws_region=aws_region or "us-west-1",
        aws_profile=aws_profile or None,
        interval_seconds=interval_seconds,
        max_files_per_run=max_files_per_run,
    ).model_dump()
    cid = connector_id or str(uuid.uuid4())
    storage.upsert_connector(cid, name, "aws_s3_access_logs", config)
    return _settings_redirect("saved (test to verify, then enable)")


@router.post("/ui/connectors/save_aws_posture")
def connector_save_aws_posture(
    connector_id: str = Form(""),
    name: str = Form(...),
    aws_profile: str = Form("blackwatch"),
    regions: str = Form(""),
    interval_seconds: int = Form(3600),
    # Phase 2a (per-region infra checks)
    check_sg_public_ingress: str = Form(""),
    check_ebs_encryption: str = Form(""),
    check_ebs_snapshot_public: str = Form(""),
    check_ec2_imdsv2: str = Form(""),
    check_ami_public: str = Form(""),
    # Phase 2b — IAM (global)
    check_iam_user_no_mfa: str = Form(""),
    check_iam_key_age: str = Form(""),
    check_iam_key_unused: str = Form(""),
    check_iam_role_wildcard_trust: str = Form(""),
    iam_key_max_age_days: int = Form(90),
    iam_key_unused_threshold_days: int = Form(90),
    # Phase 2b — KMS (per-region) + CloudTrail (global)
    check_kms_rotation: str = Form(""),
    check_kms_policy_wildcard: str = Form(""),
    check_cloudtrail_validation: str = Form(""),
    # Phase 2c — RDS
    check_rds: str = Form(""),
) -> RedirectResponse:
    region_list = [r.strip() for r in regions.split(",") if r.strip()]
    on = lambda v: v == "on"
    config = AwsPostureDriftConfig(
        aws_profile=aws_profile or None,
        regions=region_list,
        interval_seconds=interval_seconds,
        check_sg_public_ingress=on(check_sg_public_ingress),
        check_ebs_encryption=on(check_ebs_encryption),
        check_ebs_snapshot_public=on(check_ebs_snapshot_public),
        check_ec2_imdsv2=on(check_ec2_imdsv2),
        check_ami_public=on(check_ami_public),
        check_iam_user_no_mfa=on(check_iam_user_no_mfa),
        check_iam_key_age=on(check_iam_key_age),
        check_iam_key_unused=on(check_iam_key_unused),
        check_iam_role_wildcard_trust=on(check_iam_role_wildcard_trust),
        iam_key_max_age_days=iam_key_max_age_days,
        iam_key_unused_threshold_days=iam_key_unused_threshold_days,
        check_kms_rotation=on(check_kms_rotation),
        check_kms_policy_wildcard=on(check_kms_policy_wildcard),
        check_cloudtrail_validation=on(check_cloudtrail_validation),
        check_rds=on(check_rds),
    ).model_dump()
    cid = connector_id or str(uuid.uuid4())
    storage.upsert_connector(cid, name, "aws_posture_drift", config)
    return _settings_redirect("saved (test to verify, then enable)")


@router.get("/ui/aws-posture", response_class=HTMLResponse)
def aws_posture(request: Request) -> Any:
    rows = storage.list_posture_findings(unresolved_only=True)
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}
    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        counts[r["severity"]] = counts.get(r["severity"], 0) + 1
        by_type.setdefault(r["resource_type"], []).append(r)
    # Stable order: resource types sorted by count of critical+high findings desc.
    def _hotness(items: list[dict[str, Any]]) -> int:
        return sum(1 for i in items if i["severity"] in ("critical", "high"))
    by_type = dict(sorted(by_type.items(), key=lambda kv: -_hotness(kv[1])))
    have_connector = any(
        c["type"] == "aws_posture_drift" for c in storage.list_connectors()
    )
    return _TEMPLATES.TemplateResponse(
        request, "aws_posture.html",
        {"findings": rows, "counts": counts, "by_type": by_type,
         "have_connector": have_connector},
    )


@router.post("/ui/connectors/{connector_id}/test")
def connector_test(connector_id: str) -> RedirectResponse:
    result = connector_runner.run_connector(connector_id)
    if result.get("status") == "ok":
        return _settings_redirect("test ok - connector verified")
    return _settings_redirect(f"test failed: {result.get('error', 'unknown')}")


@router.post("/ui/connectors/{connector_id}/run")
def connector_run(connector_id: str) -> RedirectResponse:
    result = connector_runner.run_connector(connector_id)
    if result.get("status") == "ok":
        return _settings_redirect(f"ran ok - ingested {result.get('ingested', 0)} event(s)")
    return _settings_redirect(f"run failed: {result.get('error', 'unknown')}")


@router.post("/ui/connectors/{connector_id}/toggle")
def connector_toggle(connector_id: str, enabled: str = Form("")) -> RedirectResponse:
    storage.set_connector_enabled(connector_id, enabled == "on")
    return _settings_redirect("scheduling " + ("enabled" if enabled == "on" else "disabled"))


@router.post("/ui/connectors/{connector_id}/delete")
def connector_delete(connector_id: str) -> RedirectResponse:
    storage.delete_connector(connector_id)
    return _settings_redirect("connector deleted")
