"""HTTP surface: ingest + search. Transport lives here; it knows nothing about
event meaning beyond authenticating the source and routing to its module."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query

from . import noise, storage
from .config import settings
from .notify import router as notify_router
from .pipeline import NormalizationError, ingest_payload
from .rules import engine as rule_engine
from .rules.model import Condition

router = APIRouter()


def _module_for_token(token: str | None) -> str:
    if not token or token not in settings.token_module_map:
        raise HTTPException(status_code=401, detail="invalid or missing ingest token")
    return settings.token_module_map[token]


@router.post("/ingest", status_code=202)
def ingest(
    payload: Any = Body(...),
    x_blackwatch_token: str | None = Header(default=None),
    x_blackwatch_transport: str | None = Header(default=None),
    x_blackwatch_account: str | None = Header(default=None),
    x_blackwatch_region: str | None = Header(default=None),
) -> dict[str, Any]:
    module = _module_for_token(x_blackwatch_token)
    try:
        return ingest_payload(
            module,
            payload,
            transport=x_blackwatch_transport or "webhook",
            account=x_blackwatch_account or settings.default_account,
            region=x_blackwatch_region,
        )
    except NormalizationError as exc:
        raise HTTPException(status_code=422, detail=f"normalization failed: {exc}")


@router.get("/events")
def list_events(
    module: str | None = None,
    category: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    severity: str | None = None,
    actor_principal: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    results = storage.query_events(
        module=module,
        category=category,
        action=action,
        outcome=outcome,
        severity=severity,
        actor_principal=actor_principal,
        since=since,
        until=until,
        q=q,
        limit=limit,
    )
    return {"count": len(results), "events": results}


@router.get("/events/{event_id}")
def get_event(event_id: str) -> dict[str, Any]:
    event = storage.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event


@router.get("/overview")
def overview() -> dict[str, Any]:
    """Single endpoint that powers the Next.js / Overview page. Bundles the
    severity counts, recent notables, 24h volume, and host/posture summaries
    so the page renders with one round-trip."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    severity_counts = storage.severity_counts()
    # Hosts summary
    host_rows = storage.list_host_status()
    hosts_reporting = 0
    hosts_stale = 0
    for r in host_rows:
        age = (now - r["updated_at"]).total_seconds() if r.get("updated_at") else None
        if r.get("active") and age is not None and age <= 180:
            hosts_reporting += 1
        else:
            hosts_stale += 1
    # Posture findings counts (unresolved)
    findings = storage.list_posture_findings(unresolved_only=True)
    posture = {"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}
    for f in findings:
        sev = f.get("severity", "low")
        if sev in posture:
            posture[sev] += 1
    return {
        "now": now.isoformat(),
        "severity_counts": severity_counts,
        "notable": storage.query_events(severities=["high", "critical"], limit=10),
        "recent": storage.query_events(limit=10),
        "volume_24h": storage.event_count_since(since_24h),
        "hosts": {
            "total": len(host_rows),
            "reporting": hosts_reporting,
            "stale": hosts_stale,
        },
        "posture": {
            "total_open": len(findings),
            "by_severity": posture,
        },
    }


@router.get("/rules")
def list_rules() -> dict[str, Any]:
    rules = rule_engine.get_engine().rules
    return {
        "count": len(rules),
        "rules": [
            {
                "id": r.id,
                "title": r.title,
                "enabled": r.enabled,
                "action": r.action,
                "severity": r.severity.value if r.severity else None,
                "tags": r.tags,
            }
            for r in rules
        ],
        "muted": noise.muted_actions(),
    }


@router.post("/rules/{rule_id}/toggle")
def rule_toggle(rule_id: str, enabled: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Toggle a single rule on or off. Persists the override and updates the
    live engine in-process."""
    storage.set_rule_override(rule_id, enabled)
    rule_engine.get_engine().set_enabled(rule_id, enabled)
    return {"rule_id": rule_id, "enabled": enabled}


@router.post("/noise/mute")
def noise_mute(action: str = Body(..., embed=True)) -> dict[str, Any]:
    """Add an event action to the mute list. Muted actions are dropped at
    ingest before storage (does not reduce AWS cost — see EventBridge pattern
    in deploy/iam/ for that)."""
    action = action.strip()
    if not action:
        raise HTTPException(status_code=400, detail="action required")
    storage.add_muted_action(action)
    noise.refresh()
    return {"action": action, "muted": True}


@router.post("/noise/unmute")
def noise_unmute(action: str = Body(..., embed=True)) -> dict[str, Any]:
    storage.remove_muted_action(action)
    noise.refresh()
    return {"action": action, "muted": False}


@router.get("/connectors")
def connectors_list() -> dict[str, Any]:
    """All configured connectors with their schedule/status. The Next.js UI
    renders this at /connectors with Test / Run / Toggle / Delete actions."""
    rows = storage.list_connectors()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "enabled": r["enabled"],
            "verified": r["verified"],
            "config": r["config"],
            "last_run_at": r["last_run_at"].isoformat() if r.get("last_run_at") else None,
            "last_status": r.get("last_status"),
            "last_error": r.get("last_error"),
        })
    return {"count": len(out), "connectors": out}


@router.get("/connectors/{connector_id}")
def connector_get(connector_id: str) -> dict[str, Any]:
    c = storage.get_connector(connector_id)
    if c is None:
        raise HTTPException(status_code=404, detail="connector not found")
    return {
        "id": c["id"],
        "name": c["name"],
        "type": c["type"],
        "enabled": c["enabled"],
        "verified": c["verified"],
        "config": c["config"],
        "last_run_at": c["last_run_at"].isoformat() if c.get("last_run_at") else None,
        "last_status": c.get("last_status"),
        "last_error": c.get("last_error"),
    }


@router.get("/buckets")
def buckets_list() -> dict[str, Any]:
    """S3 bucket inventory snapshot + the public/unencrypted/no-versioning
    counters the page header displays."""
    rows = storage.list_bucket_status()
    public_count = sum(1 for b in rows if b.get("public"))
    unenc_count = sum(
        1 for b in rows if (b.get("encryption") or "none") == "none"
    )
    no_versioning_count = sum(
        1 for b in rows if (b.get("versioning") or "Disabled") != "Enabled"
    )
    return {
        "count": len(rows),
        "buckets": rows,
        "counts": {
            "total": len(rows),
            "public": public_count,
            "unencrypted": unenc_count,
            "no_versioning": no_versioning_count,
        },
    }


@router.get("/vpn")
def vpn_view(stale_after_seconds: int = 180) -> dict[str, Any]:
    """Single endpoint that powers the Next.js /vpn page — bundles server
    status (with connected clients) and recent auth attempts."""
    now = datetime.now(timezone.utc)
    servers = []
    for row in storage.list_vpn_status():
        clients = row["clients"] or []
        certs = row["certs"] or []
        age = (now - row["updated_at"]).total_seconds() if row["updated_at"] else None
        servers.append({
            "server": row["server"],
            "active": row["active"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "age_seconds": int(age) if age is not None else None,
            "stale": age is not None and age > stale_after_seconds,
            "client_count": len(clients),
            "clients": clients,
            "certs": certs,
        })
    auth = [
        e for e in storage.query_events(category="vpn", limit=200)
        if e.get("action") in ("vpn.auth.success", "vpn.auth.failure")
    ][:40]
    return {"servers": servers, "auth": auth}


@router.delete("/vpn/servers/{server}")
def vpn_server_delete(server: str) -> dict[str, Any]:
    """Drop a stale/renamed VPN server row from the read model. The next
    heartbeat from any agent under that name (if anyone's still pointing
    there) would just create a fresh row, so this is safe."""
    storage.delete_vpn_status(server)
    return {"server": server, "deleted": True}


@router.get("/vpn/status")
def vpn_status(stale_after_seconds: int = 180) -> dict[str, Any]:
    """Live view: per VPN server, is it up and who is connected right now."""
    now = datetime.now(timezone.utc)
    servers = []
    for row in storage.list_vpn_status():
        clients = row["clients"] or []
        age = (now - row["updated_at"]).total_seconds()
        servers.append(
            {
                "server": row["server"],
                "active": row["active"],
                "updated_at": row["updated_at"].isoformat(),
                "age_seconds": int(age),
                "stale": age > stale_after_seconds,
                "client_count": len(clients),
                "clients": clients,
            }
        )
    return {"servers": servers}


_HOST_STALE_AFTER = 180
_HOST_CHANGE_PREFIXES = (
    "host.port.", "host.user.", "host.authorized_key.", "host.sudoers.",
    "host.file.", "host.cron.", "host.service.", "host.suid.", "host.packages.",
)


@router.get("/hosts")
def hosts_list() -> dict[str, Any]:
    """List of all reporting hosts plus the recent host-category events used
    to render the /ui/hosts page (auth + state-change tables)."""
    now = datetime.now(timezone.utc)
    servers: list[dict[str, Any]] = []
    for row in storage.list_host_status():
        age = (now - row["updated_at"]).total_seconds() if row.get("updated_at") else None
        snaps = row.get("snapshots") or {}
        extra = row.get("extra") or {}
        tags = extra.get("tags") if isinstance(extra.get("tags"), dict) else None
        servers.append({
            "instance_id": row["instance_id"],
            "hostname": row.get("hostname"),
            "account": row.get("account"),
            "region": row.get("region"),
            "active": row.get("active"),
            "age_seconds": int(age) if age is not None else None,
            "stale": age is not None and age > _HOST_STALE_AFTER,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            "tags": tags,
            "port_count": len(snaps.get("ports") or []),
            "user_count": len(snaps.get("users") or []),
            "key_count": len(snaps.get("authorized_keys") or []),
        })
    recent = storage.query_events(category="host", limit=200)
    auth = [
        e for e in recent
        if e.get("action", "").startswith(("host.auth", "host.sudo"))
    ][:40]
    changes = [
        e for e in recent
        if e.get("action", "").startswith(_HOST_CHANGE_PREFIXES)
    ][:40]
    return {
        "count": len(servers),
        "servers": servers,
        "auth": auth,
        "changes": changes,
    }


@router.get("/hosts/{instance_id}")
def host_detail(instance_id: str) -> dict[str, Any]:
    """All data needed to render the host detail page. Returns host=null when
    the instance isn't known yet (so the UI can show an empty state)."""
    host = storage.get_host_status(instance_id)
    if host is None:
        return {
            "instance_id": instance_id,
            "host": None,
            "snapshots": {},
            "age_seconds": None,
            "stale": True,
            "auth_events": [],
            "state_changes": [],
            "alerts": [],
        }
    now = datetime.now(timezone.utc)
    age: int | None = None
    stale = False
    if host.get("updated_at"):
        age = int((now - host["updated_at"]).total_seconds())
        stale = age > _HOST_STALE_AFTER
    snapshots = host.get("snapshots") or {}
    recent = storage.query_events(target_id=instance_id, limit=150)
    return {
        "instance_id": instance_id,
        "host": host,
        "snapshots": snapshots,
        "age_seconds": age,
        "stale": stale,
        "auth_events": [
            e for e in recent
            if e.get("action", "").startswith(("host.auth", "host.sudo"))
        ][:30],
        "state_changes": [
            e for e in recent
            if e.get("action", "").startswith(_HOST_CHANGE_PREFIXES)
        ][:30],
        "alerts": [
            e for e in recent if e.get("severity") in ("high", "critical")
        ][:20],
        # FIM Part 1: coverage stats + most recent change history.
        # The full file list (fim_baselines) is per-host data and rarely needed
        # for the host page; we expose count + last-N changes here and ship the
        # full list via a separate endpoint when the UI needs it.
        "fim_coverage": storage.get_fim_coverage(instance_id),
        "fim_recent_changes": storage.list_fim_history(instance_id, limit=50),
    }


# --- File Integrity Monitoring (FIM) top-level view -------------------------

_HOST_STALE_AFTER_FIM = _HOST_STALE_AFTER  # share the EC2 staleness window


@router.get("/fim")
def fim_view() -> dict[str, Any]:
    """Top-level FIM page. Returns every host with FIM data + recent FIM
    history across all hosts. Drives /fim — the table at the top and the
    activity table below."""
    now = datetime.now(timezone.utc)
    hosts = []
    for row in storage.list_fim_hosts():
        # Compute staleness off the host's last heartbeat — coverage updates
        # ride heartbeats, so they're effectively the same number.
        age = None
        stale = False
        if row.get("host_updated_at"):
            try:
                last = datetime.fromisoformat(
                    row["host_updated_at"].replace("Z", "+00:00")
                )
                age = int((now - last).total_seconds())
                stale = age > _HOST_STALE_AFTER_FIM
            except ValueError:
                pass
        hosts.append({**row, "age_seconds": age, "stale": stale})
    return {
        "count": len(hosts),
        "hosts": hosts,
        "recent_changes": storage.list_recent_fim_history(limit=100),
    }


@router.get("/fim/{instance_id}")
def fim_instance_view(instance_id: str) -> dict[str, Any]:
    """Per-instance FIM detail. Coverage + paths-with-file-counts + recent
    history. The path summary groups baselines under each configured
    directory so the operator sees what's actually being hashed under each
    monitored prefix."""
    coverage = storage.get_fim_coverage(instance_id)
    baselines = storage.list_fim_baselines(instance_id)
    history = storage.list_fim_history(instance_id, limit=200)

    # Build path summary. The agent ships per-path file_count + total_size
    # in the heartbeat (coverage.path_stats), computed from its local
    # baseline SQLite — that's the SOURCE OF TRUTH because Postgres's
    # fim_baselines table is only populated when changes occur.
    #
    # We fall back to baseline-derived counts only when path_stats is
    # missing (e.g. agent hasn't shipped a coverage event yet, or it's
    # an old agent pre-Part-3.5).
    configured = (coverage or {}).get("configured_paths") or {}
    path_stats = (coverage or {}).get("path_stats") or {}
    summary = []
    category_labels = {
        "critical_files": "Critical files",
        "critical_dirs": "Critical directories",
        "binary_dirs": "Binary directories",
    }
    for category, label in category_labels.items():
        for entry in configured.get(category) or []:
            stats = path_stats.get(entry)
            if stats:
                file_count = int(stats.get("file_count") or 0)
                total_size = int(stats.get("total_size_bytes") or 0)
            else:
                # Fallback to baseline-derived count.
                if category == "critical_files":
                    matched = [b for b in baselines if b["path"] == entry]
                else:
                    pref = entry.rstrip("/") + "/"
                    matched = [b for b in baselines
                               if b["path"].startswith(pref) or b["path"] == entry]
                file_count = len(matched)
                total_size = sum((m["size"] or 0) for m in matched)
            summary.append({
                "category": category,
                "category_label": label,
                "path": entry,
                "file_count": file_count,
                "total_size_bytes": total_size,
            })

    # Stray baselines = files in our fim_baselines table whose path isn't
    # under any currently-configured prefix. Means the operator changed
    # the agent's config but the agent hasn't been restarted to clean up.
    # Stray detection still uses Postgres baselines (the sparse ones — but
    # they're the only baselines we know about server-side).
    seen_paths = set()
    for entry in (
        (configured.get("critical_files") or [])
        + (configured.get("critical_dirs") or [])
        + (configured.get("binary_dirs") or [])
    ):
        for b in baselines:
            if b["path"] == entry or b["path"].startswith(entry.rstrip("/") + "/"):
                seen_paths.add(b["path"])
    stray = [b for b in baselines if b["path"] not in seen_paths]

    return {
        "instance_id": instance_id,
        "coverage": coverage,
        "paths_summary": summary,
        "stray_baselines": stray[:50],   # cap so UI doesn't get blown out
        "stray_count": len(stray),
        "recent_changes": history,
    }


# --- Performance alert rules ------------------------------------------------

_VALID_PERF_METRICS = {"memory_pct", "cpu_load_norm", "disk_pct_max"}
_VALID_PERF_COMPARISONS = {"gte", "gt", "lte", "lt"}
_VALID_PERF_SEVERITIES = {"informational", "low", "medium", "high", "critical"}


@router.get("/perf-alerts")
def perf_alerts_list() -> dict[str, Any]:
    """All perf alert rules + the list of instances available to scope
    new rules to (used by the wizard's dropdown)."""
    rules = storage.list_perf_alert_rules()
    # Build instance dropdown: every host that's reporting, with display tags.
    instances = []
    for h in storage.list_host_status():
        extra = h.get("extra") or {}
        tags = extra.get("tags") if isinstance(extra.get("tags"), dict) else None
        instances.append({
            "instance_id": h["instance_id"],
            "hostname": h.get("hostname"),
            "tags": tags,
        })
    # Channels available — for the dropdown.
    channels = [
        {"id": str(c["id"]), "name": c["name"], "type": c.get("type"),
         "enabled": c.get("enabled", True)}
        for c in storage.list_notification_channels()
    ]
    return {
        "rules": rules,
        "instances": instances,
        "channels": channels,
    }


@router.get("/perf-alerts/{rule_id}")
def perf_alerts_get(rule_id: str) -> dict[str, Any]:
    rule = storage.get_perf_alert_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@router.post("/perf-alerts")
def perf_alerts_create(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a new perf alert rule. Validation is permissive on display
    fields (name, severity), strict on semantic fields (metric, scope)."""
    rule_id = payload.get("id") or str(__import__("uuid").uuid4())
    _validate_perf_payload(payload)
    storage.upsert_perf_alert_rule(
        rule_id,
        name=str(payload["name"]).strip(),
        enabled=bool(payload.get("enabled", True)),
        module=payload.get("module") or "ec2.host",
        instance_id=(payload.get("instance_id") or None),
        tag_key=(payload.get("tag_key") or None),
        tag_value=(payload.get("tag_value") or None),
        metric=payload["metric"],
        comparison=payload.get("comparison", "gte"),
        threshold=float(payload["threshold"]),
        window_seconds=int(payload.get("window_seconds", 300)),
        min_breach_ratio=float(payload.get("min_breach_ratio", 0.6)),
        severity=payload.get("severity", "high"),
        channels=list(payload.get("channels") or []),
        throttle_seconds=int(payload.get("throttle_seconds", 1800)),
    )
    return {"id": rule_id}


@router.put("/perf-alerts/{rule_id}")
def perf_alerts_update(
    rule_id: str, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    if storage.get_perf_alert_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail="rule not found")
    _validate_perf_payload(payload)
    storage.upsert_perf_alert_rule(
        rule_id,
        name=str(payload["name"]).strip(),
        enabled=bool(payload.get("enabled", True)),
        module=payload.get("module") or "ec2.host",
        instance_id=(payload.get("instance_id") or None),
        tag_key=(payload.get("tag_key") or None),
        tag_value=(payload.get("tag_value") or None),
        metric=payload["metric"],
        comparison=payload.get("comparison", "gte"),
        threshold=float(payload["threshold"]),
        window_seconds=int(payload.get("window_seconds", 300)),
        min_breach_ratio=float(payload.get("min_breach_ratio", 0.6)),
        severity=payload.get("severity", "high"),
        channels=list(payload.get("channels") or []),
        throttle_seconds=int(payload.get("throttle_seconds", 1800)),
    )
    return {"id": rule_id}


@router.delete("/perf-alerts/{rule_id}")
def perf_alerts_delete(rule_id: str) -> dict[str, Any]:
    storage.delete_perf_alert_rule(rule_id)
    return {"ok": True}


_PERF_QUICK_METRICS = {
    "memory_pct": {
        "label": "Memory used %",
        "blurb": "Alert when total RAM utilisation stays high.",
        "default_threshold": 85,
        "default_window_minutes": 5,
        "default_severity": "high",
    },
    "cpu_load_norm": {
        "label": "CPU load (normalised)",
        "blurb": "1-minute load average / CPU count, as a %.",
        "default_threshold": 90,
        "default_window_minutes": 10,
        "default_severity": "high",
    },
    "disk_pct_max": {
        "label": "Disk used % (worst mount)",
        "blurb": "Highest used % across all mounts on the host.",
        "default_threshold": 85,
        "default_window_minutes": 15,
        "default_severity": "high",
    },
}
_PERF_QUICK_NAMESPACE = uuid.UUID("7c8b1d0e-d0b0-4a5f-b1a5-2a3e2f9c9c9c")


def _perf_quick_rule_id(metric: str, scope_key: str) -> str:
    return str(uuid.uuid5(
        _PERF_QUICK_NAMESPACE, f"auto:perf:{metric}:{scope_key}"
    ))


@router.get("/notifications/perf-alerts/quick")
def perf_alerts_quick_list() -> dict[str, Any]:
    """Return one entry per metric with defaults + any existing card-saved
    rule for it. Populates the /notifications/perf-alerts/quick UI."""
    channels = [
        {"name": c["name"], "type": c.get("type"), "enabled": c.get("enabled", True)}
        for c in storage.list_notification_channels()
    ]
    instances = []
    for h in storage.list_host_status():
        instances.append({
            "instance_id": h["instance_id"],
            "hostname": h.get("hostname"),
        })
    # Map existing rules by their auto:perf: id so a card can reflect them.
    rules_by_metric: dict[str, list[dict[str, Any]]] = {}
    for r in storage.list_perf_alert_rules():
        name = (r.get("name") or "")
        if not name.startswith("auto:perf:"):
            continue
        metric = r.get("metric")
        rules_by_metric.setdefault(metric, []).append(r)
    cards = []
    for key, spec in _PERF_QUICK_METRICS.items():
        cards.append({
            "metric": key,
            **spec,
            "existing": rules_by_metric.get(key, []),
        })
    return {"cards": cards, "channels": channels, "instances": instances}


@router.post("/notifications/perf-alerts/quick")
def perf_alerts_quick_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Upsert a single quick perf-alert card.

    Payload:
      metric          — one of _PERF_QUICK_METRICS keys
      threshold       — number
      window_minutes  — int (converted to window_seconds)
      scope           — "all" | "instance"
      instance_id     — required when scope == "instance"
      channel         — channel name (required unless disabling)
      enabled         — bool, defaults true
      severity        — optional; falls back to the metric's default
    """
    metric = str(payload.get("metric") or "")
    if metric not in _PERF_QUICK_METRICS:
        raise HTTPException(status_code=400, detail=f"unknown metric {metric!r}")
    scope = str(payload.get("scope") or "all")
    instance_id = payload.get("instance_id") or None
    if scope == "instance" and not instance_id:
        raise HTTPException(status_code=400, detail="instance_id required for scope=instance")
    scope_key = f"instance-{instance_id}" if scope == "instance" else "all"
    channel = payload.get("channel") or None
    if channel is not None:
        channel = str(channel).strip() or None
    rule_id = _perf_quick_rule_id(metric, scope_key)

    # No channel = delete the card so it stops firing.
    if not channel:
        storage.delete_perf_alert_rule(rule_id)
        return {"id": rule_id, "deleted": True}

    spec = _PERF_QUICK_METRICS[metric]
    threshold = float(payload.get("threshold") or spec["default_threshold"])
    window_minutes = int(payload.get("window_minutes") or spec["default_window_minutes"])
    severity = str(payload.get("severity") or spec["default_severity"])
    scope_suffix = "all hosts" if scope == "all" else instance_id
    name = f"auto:perf:{metric} · {scope_suffix}"

    storage.upsert_perf_alert_rule(
        rule_id,
        name=name,
        enabled=bool(payload.get("enabled", True)),
        module="ec2.host",
        instance_id=(instance_id if scope == "instance" else None),
        tag_key=None,
        tag_value=None,
        metric=metric,
        comparison="gte",
        threshold=threshold,
        window_seconds=max(60, window_minutes * 60),
        min_breach_ratio=0.6,
        severity=severity,
        channels=[channel],
        throttle_seconds=1800,
    )
    return {"id": rule_id, "saved": True}


def _validate_perf_payload(p: dict[str, Any]) -> None:
    if not p.get("name") or not str(p["name"]).strip():
        raise HTTPException(status_code=400, detail="name is required")
    metric = p.get("metric")
    if metric not in _VALID_PERF_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"metric must be one of {sorted(_VALID_PERF_METRICS)}",
        )
    comparison = p.get("comparison", "gte")
    if comparison not in _VALID_PERF_COMPARISONS:
        raise HTTPException(
            status_code=400,
            detail=f"comparison must be one of {sorted(_VALID_PERF_COMPARISONS)}",
        )
    sev = p.get("severity", "high")
    if sev not in _VALID_PERF_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"severity must be one of {sorted(_VALID_PERF_SEVERITIES)}",
        )
    if p.get("threshold") is None:
        raise HTTPException(status_code=400, detail="threshold is required")
    # Scope: must pick instance OR tag pair (avoid fleet-wide alerts by
    # accident — easy to add explicitly later if needed).
    has_instance = bool(p.get("instance_id"))
    has_tag = bool(p.get("tag_key")) and p.get("tag_value") is not None
    if not has_instance and not has_tag:
        raise HTTPException(
            status_code=400,
            detail="scope required: either instance_id or (tag_key + tag_value)",
        )
    if has_instance and has_tag:
        raise HTTPException(
            status_code=400,
            detail="scope conflict: set instance_id OR tag, not both",
        )
    try:
        ws = int(p.get("window_seconds", 300))
        if ws < 60:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="window_seconds must be >= 60")
    try:
        ratio = float(p.get("min_breach_ratio", 0.6))
        if not (0 < ratio <= 1):
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="min_breach_ratio must be in (0, 1]")
    try:
        ts = int(p.get("throttle_seconds", 1800))
        if ts < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="throttle_seconds must be >= 0")


_SERVICE_ARCHIVE_AFTER = timedelta(days=7)


@router.get("/services")
def services_list() -> dict[str, Any]:
    """Probe-target inventory grouped by VPC, joined with current status, plus
    the per-VPC probe-agent health table.

    Services in `down`/`degraded` for >= _SERVICE_ARCHIVE_AFTER are split out
    into a single `archived` list so the per-VPC tables stay focused on the
    live surface. Archived services rejoin their VPC's grouping the moment
    they probe `up` again (down_since clears, archive predicate fails)."""
    now = datetime.now(timezone.utc)
    targets = {t["id"]: t for t in storage.list_probe_targets()}
    statuses = {s["target_id"]: s for s in storage.list_service_status()}
    rows: list[dict[str, Any]] = []
    for tid, t in targets.items():
        s = statuses.get(tid)
        last_seen_dt = (s or {}).get("last_seen")
        down_since_dt = (s or {}).get("down_since")
        if last_seen_dt:
            age = int((now - last_seen_dt).total_seconds())
            stale = age > _HOST_STALE_AFTER
        else:
            age = None
            stale = True
        rows.append({
            **t,
            "status": (s or {}).get("status") or "unknown",
            "last_seen": last_seen_dt.isoformat() if last_seen_dt else None,
            "age_seconds": age,
            "stale": stale,
            "latency_ms": (s or {}).get("latency_ms"),
            "consecutive_fails": (s or {}).get("consecutive_fails") or 0,
            "down_since": down_since_dt.isoformat() if down_since_dt else None,
        })

    # Effective status for non-probed targets:
    #   * desiredCount=0   -> 'disabled' (operator turned it off -> archive)
    #   * everything else  -> 'unknown'  (we can't probe it, but AWS still
    #                                     wants it running -> stays in live
    #                                     table with aws_desired/aws_running
    #                                     visible)
    # The stored last_seen / latency / fails are stale by definition once we
    # stopped probing -- clear them so the UI doesn't display ghost data.
    for r in rows:
        if not r.get("enabled"):
            aws_desired = (r.get("tags") or {}).get("aws_desired", "1")
            r["status"] = "disabled" if aws_desired == "0" else "unknown"
            r["latency_ms"] = None
            r["consecutive_fails"] = 0
            r["last_seen"] = None
            r["age_seconds"] = None
            r["stale"] = False

    def _is_archived(r: dict[str, Any]) -> bool:
        # Disabled = aws_desired==0 = operator turned it off -> archive.
        # Unknown stays in the live table (operator wants to see AWS state).
        if r["status"] == "disabled":
            return True
        if r["status"] not in ("down", "degraded"):
            return False
        # Fast path retained for safety: an enabled target whose tag still
        # says aws_desired==0 (e.g. a stale row before the next sync) is
        # still treated as archived.
        if (r.get("tags") or {}).get("aws_desired") == "0":
            return True
        ds = (statuses.get(r["id"]) or {}).get("down_since")
        return bool(ds and (now - ds) >= _SERVICE_ARCHIVE_AFTER)

    archived = [r for r in rows if _is_archived(r)]
    live = [r for r in rows if not _is_archived(r)]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in live:
        grouped.setdefault(r["vpc"], []).append(r)
    # Sort each VPC's table: DOWN/degraded first, unknown next, up next,
    # disabled sinks to the bottom (it's inventory, not a live signal).
    _STATUS_ORDER = {"down": 0, "degraded": 1, "unknown": 2, "up": 3, "disabled": 9}
    for vpc_rows in grouped.values():
        vpc_rows.sort(key=lambda r: (
            _STATUS_ORDER.get(r["status"], 5), r["tier"], r["name"].lower(),
        ))
    archived.sort(key=lambda r: (r["vpc"], r["tier"], r["name"].lower()))

    # Per-VPC count summary for the panel headers. Disabled is its own bucket
    # so the user can see "5 disabled" without it muddying the up/down ratio.
    counts: dict[str, dict[str, int]] = {}
    for vpc, vpc_rows in grouped.items():
        c = {"total": len(vpc_rows), "up": 0, "down": 0, "degraded": 0,
             "unknown": 0, "disabled": 0}
        for r in vpc_rows:
            c[r["status"]] = c.get(r["status"], 0) + 1
        counts[vpc] = c

    agents = []
    for a in storage.list_probe_agents():
        last_report = a["last_report"].isoformat() if a.get("last_report") else None
        agents.append({
            "vpc": a["vpc"],
            "active": a.get("active"),
            "agent_version": a.get("agent_version"),
            "last_report": last_report,
        })
    return {
        "agents": agents,
        "grouped": grouped,
        "counts": counts,
        "archived": archived,
        "archive_threshold_days": int(_SERVICE_ARCHIVE_AFTER.total_seconds() // 86400),
    }


_HOST_AUTH_ACTIONS = {
    "host.auth.ssh.success", "host.auth.ssh.failure",
    "host.sudo.exec", "host.sudo.failure",
}
_VPN_AUTH_ACTIONS = {"vpn.auth.success", "vpn.auth.failure"}
_HOST_CHANGE_PREFIXES = (
    "host.authorized_key.", "host.user.", "host.sudoers.",
    "host.port.", "host.suid.", "host.cron.", "host.file.",
    "host.service.", "host.packages.",
)
_STORAGE_EXPOSURE_ACTIONS = {
    "s3.bucket.acl.put",
    "s3.bucket.policy.put",
    "s3.bucket.bpa.put",
    "s3.bucket.bpa.delete",
    "s3.bucket.encryption.delete",
    "s3.bucket.versioning.put",  # only if suspended — UI filters on extras
    "storage.snapshot.modify",
    "compute.ami.modify",
    "compute.imds.modify",
    # RDS — only include the events that meaningfully change exposure. Routine
    # instance create / reboot stays in /events. Snapshot.modify is the data-
    # sharing surface; instance.modify carries publicly_accessible toggles.
    "rds.instance.create",
    "rds.instance.modify",
    "rds.cluster.create",
    "rds.cluster.modify",
    "rds.snapshot.modify",
    "rds.cluster_snapshot.modify",
    "rds.parameter_group.modify",  # for the security-relevant param flag
}


@router.get("/iam")
def iam_view() -> dict[str, Any]:
    """The AWS control-plane view. Everything that flows in through
    CloudTrail → EventBridge → Lambda → SQS lands here: console + federated
    logins, IAM identity / credential / policy changes, security-group rule
    changes, VPC/IGW/route/peering topology changes, KMS key & grant changes,
    storage-exposure flips, CloudTrail-tamper.

    Explicitly EXCLUDED here: host SSH/sudo auth, OpenVPN auth, host posture
    changes — those don't come from CloudTrail. The /hosts and /vpn pages own
    those signals; mixing them here would dilute the "what did AWS itself
    record?" view.

    Single broad query → filter in Python per bucket. One DB hit.
    """
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    # One broad pull. Covers both counters and the per-section filters.
    recent = storage.query_events(limit=3000)

    # event_time in the envelope JSONB is an ISO string; can't compare with
    # a datetime directly. Parse it once per row.
    def _ts_in_window(row: dict[str, Any]) -> bool:
        ts = row.get("event_time")
        if isinstance(ts, datetime):
            return ts >= since_24h
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return False
            return parsed >= since_24h
        return False

    def _login_kind(row: dict[str, Any]) -> str:
        """iam | root | sso. The adapter sets extra.login_kind; fall back to
        actor.is_root for older events that pre-date that field."""
        extra = row.get("extra") or {}
        if isinstance(extra, dict) and extra.get("login_kind"):
            return str(extra["login_kind"])
        actor = row.get("actor") or {}
        if isinstance(actor, dict) and actor.get("is_root"):
            return "root"
        return "iam"

    def _mfa_disabled(row: dict[str, Any]) -> bool:
        return row.get("action") in ("iam.mfa.deactivate", "iam.mfa.delete")

    recent_24h = [r for r in recent if _ts_in_window(r)]

    # 24h counters — CloudTrail-sourced only.
    counts = {
        "logins_ok": 0,
        "logins_failed": 0,
        "logins_root": 0,
        "logins_sso": 0,
        "iam_changes": 0,
        "mfa_disabled": 0,
        "sg_changes": 0,
        "network_topology": 0,
        "kms_changes": 0,
        "storage_exposure": 0,
        "ct_tamper": 0,
        "posture_findings_new": 0,
    }
    for e in recent_24h:
        action = e.get("action", "")
        outcome = e.get("outcome")
        if action == "auth.console.login":
            if outcome == "success":
                counts["logins_ok"] += 1
            else:
                counts["logins_failed"] += 1
            if _login_kind(e) == "root":
                counts["logins_root"] += 1
        elif action == "auth.federated.login":
            counts["logins_sso"] += 1
            if outcome != "success":
                counts["logins_failed"] += 1
        elif action.startswith("iam."):
            counts["iam_changes"] += 1
            if _mfa_disabled(e):
                counts["mfa_disabled"] += 1
        elif action.startswith("kms."):
            counts["kms_changes"] += 1
        elif action.startswith("network.sg."):
            counts["sg_changes"] += 1
        elif action.startswith("network."):
            counts["network_topology"] += 1
        elif action in _STORAGE_EXPOSURE_ACTIONS:
            counts["storage_exposure"] += 1
        elif action.startswith("cloudtrail."):
            counts["ct_tamper"] += 1
        elif action == "aws.posture.finding.new":
            counts["posture_findings_new"] += 1

    def _bucket(predicate, cap: int) -> list[dict[str, Any]]:
        return [r for r in recent if predicate(r)][:cap]

    logins = _bucket(
        lambda r: r.get("action") in ("auth.console.login", "auth.federated.login"),
        50,
    )

    iam_changes = _bucket(
        lambda r: r.get("action", "").startswith("iam."),
        50,
    )

    sg_changes = _bucket(
        lambda r: r.get("action", "").startswith("network.sg."),
        50,
    )

    # network topology = network.* MINUS network.sg.* (which has its own bucket)
    network_topology = _bucket(
        lambda r: (a := r.get("action", "")).startswith("network.")
        and not a.startswith("network.sg."),
        50,
    )

    storage_exposure = _bucket(
        lambda r: r.get("action") in _STORAGE_EXPOSURE_ACTIONS,
        30,
    )

    kms_changes = _bucket(
        lambda r: r.get("action", "").startswith("kms."),
        30,
    )

    posture_findings_new = _bucket(
        lambda r: r.get("action") == "aws.posture.finding.new",
        30,
    )

    ct_tamper = _bucket(
        lambda r: r.get("action", "").startswith("cloudtrail."),
        20,
    )

    return {
        "counts": counts,
        "logins": logins,
        "iam_changes": iam_changes,
        "sg_changes": sg_changes,
        "network_topology": network_topology,
        "storage_exposure": storage_exposure,
        "kms_changes": kms_changes,
        "posture_findings_new": posture_findings_new,
        "ct_tamper": ct_tamper,
    }


@router.get("/rds")
def rds_view() -> dict[str, Any]:
    """Single endpoint that powers the Next.js /rds page.

    Event-driven: we don't (yet) have a drift connector that polls
    DescribeDBInstances, so the inventory shown here is "instances BlackWatch
    has seen CloudTrail events for in the last N days." A DB that never
    changes never appears — that's a real gap to close with a drift connector
    later. Until then, the /iam page already surfaces the security-signal
    events; this page just groups them by DB so you can see per-instance
    posture at a glance.
    """
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_30d = now - timedelta(days=30)

    # Broad pull; filter by action prefix in Python.
    all_events = storage.query_events(limit=2000)
    rds_events = [e for e in all_events if e.get("action", "").startswith("rds.")]

    def _ts(row: dict[str, Any]) -> datetime | None:
        ts = row.get("event_time")
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _in(window_start: datetime, row: dict[str, Any]) -> bool:
        t = _ts(row)
        return t is not None and t >= window_start

    recent_24h = [r for r in rds_events if _in(since_24h, r)]
    recent_30d = [r for r in rds_events if _in(since_30d, r)]

    # Counters: 24h volume + "exposure flags ever seen in 30d" (so a public
    # DB stays visible until BlackWatch sees the fix come through).
    def _has_flag(row: dict[str, Any], flag: str) -> bool:
        extras = (row.get("envelope") or {}).get("extra") or row.get("extra") or {}
        return bool(extras.get(flag))

    flagged_public = {r.get("target_id") for r in recent_30d if _has_flag(r, "rds_publicly_accessible")}
    flagged_no_backups = {r.get("target_id") for r in recent_30d if _has_flag(r, "rds_backups_disabled")}
    flagged_unencrypted = {r.get("target_id") for r in recent_30d if _has_flag(r, "rds_unencrypted_at_creation")}
    flagged_snap_public = {r.get("target_id") for r in recent_30d if _has_flag(r, "rds_snapshot_made_public")}
    flagged_no_del_protect = {r.get("target_id") for r in recent_30d if _has_flag(r, "rds_deletion_protection_off")}

    counts = {
        "events_24h": len(recent_24h),
        "instances_seen": len({r.get("target_id") for r in recent_30d if r.get("target_id")}),
        "public_flagged": len(flagged_public - {None}),
        "no_backups_flagged": len(flagged_no_backups - {None}),
        "unencrypted_flagged": len(flagged_unencrypted - {None}),
        "snapshot_public_flagged": len(flagged_snap_public - {None}),
        "no_deletion_protection_flagged": len(flagged_no_del_protect - {None}),
    }

    # Per-instance summary — latest event per target_id, plus the set of flags
    # ever seen for that instance in the last 30d.
    by_instance: dict[str, dict[str, Any]] = {}
    for r in recent_30d:
        tid = r.get("target_id")
        if not tid:
            continue
        entry = by_instance.setdefault(tid, {
            "instance_id": tid,
            "events_30d": 0,
            "last_event_time": None,
            "last_action": None,
            "last_actor": None,
            "flags": set(),
        })
        entry["events_30d"] += 1
        ts = _ts(r)
        if ts and (entry["last_event_time"] is None or ts > entry["last_event_time"]):
            entry["last_event_time"] = ts
            entry["last_action"] = r.get("action")
            entry["last_actor"] = r.get("actor_principal")
        extras = (r.get("envelope") or {}).get("extra") or r.get("extra") or {}
        for k, v in extras.items():
            if k.startswith("rds_") and v:
                entry["flags"].add(k)

    instances = []
    for entry in by_instance.values():
        instances.append({
            "instance_id": entry["instance_id"],
            "events_30d": entry["events_30d"],
            "last_event_time": entry["last_event_time"].isoformat() if entry["last_event_time"] else None,
            "last_action": entry["last_action"],
            "last_actor": entry["last_actor"],
            "flags": sorted(entry["flags"]),
        })
    instances.sort(key=lambda x: x["last_event_time"] or "", reverse=True)

    # Recent events table — last 50.
    recent_events = recent_24h[:50]

    # Connector wired up?
    have_connector = any(
        c.get("type") == "aws_cloudtrail_sqs" and c.get("enabled")
        for c in storage.list_connectors()
    )

    return {
        "counts": counts,
        "instances": instances,
        "recent_events": recent_events,
        "have_connector": have_connector,
    }


@router.get("/posture/findings")
def posture_findings(
    unresolved_only: bool = True,
    resource_type: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """AWS posture findings — drift-detected, current state. The UI uses this
    to render the per-resource-type tables on /ui/aws-posture (and its Next.js
    successor /aws-posture)."""
    findings = storage.list_posture_findings(
        unresolved_only=unresolved_only,
        resource_type=resource_type,
        account=account,
    )
    have_connector = any(
        c["type"] == "aws_posture_drift" for c in storage.list_connectors()
    )
    return {
        "count": len(findings),
        "findings": findings,
        "have_connector": have_connector,
    }


@router.get("/posture/findings/{finding_id}")
def posture_finding_detail(finding_id: str) -> dict[str, Any]:
    finding = storage.get_posture_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return finding


@router.get("/channels")
def list_channels() -> dict[str, Any]:
    notifier = notify_router.get_notifier()
    return {
        "channels": [
            {"name": c.name, "type": c.type, "enabled": c.enabled}
            for c in notifier.channels.values()
        ]
    }


@router.get("/routes")
def list_routes() -> dict[str, Any]:
    notifier = notify_router.get_notifier()
    return {
        "routes": [
            {
                "name": r.name,
                "enabled": r.enabled,
                "min_severity": r.min_severity.value if r.min_severity else None,
                "channels": r.channels,
            }
            for r in notifier.routes
        ]
    }


@router.post("/notifications/test")
def test_notification(channel: str) -> dict[str, Any]:
    return notify_router.get_notifier().send_test(channel)


# ---------- Notifications (DB-backed) — list / read / save / mutate ---------
# Mutation endpoints accept JSON bodies so the Next.js UI can ship per-type
# channel config dicts and Condition trees without a YAML textarea.

@router.get("/notifications/templates")
def notif_templates(channel_type: str | None = None) -> dict[str, Any]:
    """Named message templates per channel type. Powers the UI's template
    picker so users can choose a friendly layout instead of writing Jinja by
    hand. Pass ?channel_type=slack to fetch just one type's presets."""
    from .notify.channels import TEMPLATE_PRESETS
    if channel_type:
        return {"type": channel_type, "presets": TEMPLATE_PRESETS.get(channel_type, [])}
    return {"presets_by_type": TEMPLATE_PRESETS}


@router.post("/notifications/templates/preview")
def notif_template_preview(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Render a Jinja template against a synthetic sample event so the UI can
    show the operator what their message will look like before they save.
    Renders are best-effort: a bad template returns the Jinja error string
    instead of raising — surfacing the error inline is the point.

    Accepts:
      template       — Jinja source. If empty/null, falls back to the
                       default template for `channel_type` (so you can
                       preview the built-in friendly preset without
                       pasting it).
      channel_type   — slack | discord | teams | email | pagerduty | webhook
      sample_event   — perf_alert | fim_modified | ssh_failure | vpn_failure
                       (default: vpn_failure for backward compat)
      sample_action  — override the action name on the sample (kept for compat)
    """
    from jinja2 import ChainableUndefined, Environment
    from .event import Event, Source, Actor, Target, Severity, Outcome, Category
    from .notify import channels as channels_module

    channel_type = str(payload.get("channel_type") or "slack").lower()
    template = str(payload.get("template") or "").strip()
    # Empty / null template → preview the channel-type default. Lets the UI
    # show "what the built-in preset looks like" without sending a copy.
    if not template:
        template = channels_module._DEFAULT_TEMPLATES.get(channel_type) or ""
    if not template:
        return {"rendered": "", "error": None}

    sample_kind = str(payload.get("sample_event") or "vpn_failure").lower()
    sample = _build_preview_sample(sample_kind, payload)

    env = Environment(autoescape=False, undefined=ChainableUndefined, trim_blocks=True)
    try:
        rendered = env.from_string(template).render(
            event=sample.model_dump(mode="json"),
            channel_name=str(payload.get("channel_name") or "preview"),
        )
        return {"rendered": rendered, "error": None}
    except Exception as exc:
        return {"rendered": "", "error": f"{exc.__class__.__name__}: {exc}"}


def _build_preview_sample(kind: str, payload: dict[str, Any]):
    """Hand-crafted sample events for the template preview. One per
    interesting event shape so the user can see how their template
    renders without firing a real event."""
    from .event import Event, Source, Actor, Target, Severity, Outcome, Category

    sample_action = payload.get("sample_action")

    if kind == "perf_alert":
        return Event(
            source=Source(module="ec2.host", transport="queue", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.host,
            action=sample_action or "host.perf.alert",
            outcome=Outcome.failure,
            severity=Severity.high,
            target=Target(id="i-03499c8ce39a70d21", type="ec2.instance",
                          name="ip-172-16-1-97.us-west-1.compute.internal"),
            extra={
                "metric": "cpu_load_norm",
                "metric_label": "CPU (normalized load)",
                "rule_id": "preview-rule-id",
                "rule_name": "CPU load (normalized) ≥ 80% on Mgmt-NAT EC2 for 5 minutes",
                "threshold": 80,
                "comparison": "gte",
                "current_value": 98.0,
                "window_seconds": 300,
                "min_breach_ratio": 0.6,
                "message": "CPU (normalized load) ≥ 80% for 5m (current: 98.0%)",
                "tags": {"env": "Mgmt", "role": "Mgmt-NAT"},
            },
        )

    if kind == "fim_modified":
        return Event(
            source=Source(module="ec2.host", transport="queue", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.host,
            action=sample_action or "host.fim.modified",
            outcome=Outcome.success,
            severity=Severity.critical,
            actor=Actor(principal="tee uid=0"),
            target=Target(id="i-03499c8ce39a70d21", type="ec2.instance",
                          name="ip-172-16-1-97.us-west-1.compute.internal"),
            extra={
                "path": "/etc/sudoers.d/bw-test",
                "change_type": "modified",
                "sha256_before": "7dd5d071...",
                "sha256_after": "998699d9...",
                "detection": "inotify",
                "actor": {"uid": 0, "pid": 8377, "comm": "tee",
                          "exe": "/usr/bin/tee",
                          "proctitle": "tee -a /etc/sudoers.d/bw-test"},
                "tags": {"env": "Mgmt", "role": "Mgmt-NAT"},
            },
        )

    if kind == "ssh_failure":
        return Event(
            source=Source(module="ec2.host", transport="queue", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.host,
            action=sample_action or "host.auth.ssh.failure",
            outcome=Outcome.failure,
            severity=Severity.low,
            actor=Actor(principal="root", source_ip="118.193.61.170"),
            target=Target(id="i-03499c8ce39a70d21", type="ec2.instance",
                          name="ip-172-16-1-97"),
            extra={
                "method": "publickey",
                "tags": {"env": "Mgmt", "role": "Mgmt-NAT"},
            },
        )

    if kind == "iam_key_created":
        return Event(
            source=Source(module="aws.cloudtrail", transport="queue",
                          account="095899260107", vendor="aws", region="us-east-1"),
            category=Category.iam,
            action=sample_action or "iam.access_key.create",
            outcome=Outcome.success,
            severity=Severity.high,
            actor=Actor(principal="arn:aws:iam::095899260107:user/deploy-bot",
                        source_ip="18.204.55.12"),
            target=Target(id="AKIA...NEW", type="iam.access_key",
                          name="deploy-bot"),
            extra={
                "message": "New access key AKIA...NEW created for IAM user deploy-bot",
                "tags": {"env": "prod", "account": "prod-mgmt"},
            },
        )

    if kind == "rds_auth_failure":
        return Event(
            source=Source(module="aws.rds", transport="queue",
                          account="095899260107", vendor="aws", region="us-west-1"),
            category=Category.auth,
            action=sample_action or "rds.auth.failure",
            outcome=Outcome.failure,
            severity=Severity.high,
            actor=Actor(principal="vikyath_shetty", source_ip="172.16.1.97"),
            target=Target(id="prod-database-healthlake",
                          type="rds.db", name="prod-database-healthlake"),
            extra={
                "db_instance": "prod-database-healthlake",
                "source_type": "rds_proxy",
                "user": "vikyath_shetty",
                "source_ip": "172.16.1.97",
                "reason": "invalid_credentials",
                "message": "prod-database-healthlake: failed proxy login for vikyath_shetty from 172.16.1.97",
                "tags": {"env": "prod", "db_instance": "prod-database-healthlake"},
            },
        )

    # Default: VPN auth failure (kept for backward compat with UI callers).
    return Event(
        source=Source(module="vpn.openvpn", transport="queue", account="prod"),
        category=Category.vpn,
        action=sample_action or "vpn.auth.failure",
        outcome=Outcome.failure,
        severity=Severity.high,
        actor=Actor(principal="apoorvasharma", source_ip="27.58.20.140"),
        target=Target(id="openvpn-prod-1", type="vpn.server", name="openvpn-prod-1"),
        rule_matches=["Failed logins"],
        tags=["vpn", "auth"],
    )


@router.get("/notifications/channels")
def notif_channels_list() -> dict[str, Any]:
    rows = storage.list_notification_channels()
    out = []
    for r in rows:
        out.append({
            **r,
            "last_sent_at": r["last_sent_at"].isoformat() if r.get("last_sent_at") else None,
        })
    return {"count": len(out), "channels": out}


@router.get("/notifications/channels/{channel_id}")
def notif_channel_get(channel_id: str) -> dict[str, Any]:
    row = storage.get_notification_channel(channel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channel not found")
    row["last_sent_at"] = row["last_sent_at"].isoformat() if row.get("last_sent_at") else None
    return row


_CHANNEL_TYPES = {"slack", "webhook", "email", "pagerduty", "teams", "discord"}


@router.post("/notifications/channels/save")
def notif_channel_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    import uuid as _uuid
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    ctype = str(payload.get("type", "")).strip()
    if ctype not in _CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown type: {ctype}")
    cid = str(payload.get("id") or "").strip() or str(_uuid.uuid4())
    config = payload.get("config") or {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="config must be an object")
    storage.upsert_notification_channel(
        channel_id=cid,
        name=name,
        ctype=ctype,
        enabled=bool(payload.get("enabled", True)),
        config=config,
        message_template=payload.get("message_template") or None,
        retries=int(payload.get("retries", 3)),
        retry_backoff_seconds=int(payload.get("retry_backoff_seconds", 5)),
        rate_limit_per_min=int(payload.get("rate_limit_per_min", 0)),
        dedup_window_seconds=int(payload.get("dedup_window_seconds", 300)),
        digest_window_seconds=int(payload.get("digest_window_seconds", 0)),
    )
    notify_router.get_notifier().reload_channels()
    return {"id": cid, "saved": True}


@router.post("/notifications/channels/{channel_id}/toggle")
def notif_channel_toggle_json(
    channel_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    storage.set_notification_channel_enabled(channel_id, enabled)
    notify_router.get_notifier().reload_channels()
    return {"id": channel_id, "enabled": enabled}


@router.post("/notifications/channels/{channel_id}/test")
def notif_channel_test_json(channel_id: str) -> dict[str, Any]:
    row = storage.get_notification_channel(channel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return notify_router.get_notifier().send_test(row["name"])


@router.delete("/notifications/channels/{channel_id}")
def notif_channel_delete(channel_id: str) -> dict[str, Any]:
    storage.delete_notification_channel(channel_id)
    notify_router.get_notifier().reload_channels()
    return {"id": channel_id, "deleted": True}


# --- Notification rules ----------------------------------------------------

@router.get("/notifications/rules")
def notif_rules_list(include_auto: bool = False) -> dict[str, Any]:
    """List rules for the advanced view. Rules whose name starts with `auto:`
    are managed by the module cards page and hidden by default; pass
    include_auto=true to see them (e.g. for debugging)."""
    from .notify import routing_matrix
    rows = storage.list_notification_rules()
    out = []
    now_utc = datetime.now(timezone.utc)
    for r in rows:
        if not include_auto and routing_matrix.is_auto_rule_name(r.get("name")):
            continue
        silence_until = r.get("silence_until")
        out.append({
            **r,
            "silence_until": silence_until.isoformat() if silence_until else None,
            "silenced": bool(silence_until and silence_until > now_utc),
        })
    return {"count": len(out), "rules": out}


@router.get("/notifications/rules/{rule_id}")
def notif_rule_get(rule_id: str) -> dict[str, Any]:
    row = storage.get_notification_rule(rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    silence_until = row.get("silence_until")
    row["silence_until"] = silence_until.isoformat() if silence_until else None
    row["silenced"] = bool(silence_until and silence_until > datetime.now(timezone.utc))
    return row


@router.post("/notifications/rules/save")
def notif_rule_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    import uuid as _uuid
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    match = payload.get("match") or {}
    if not isinstance(match, dict):
        raise HTTPException(status_code=400, detail="match must be an object")
    try:
        Condition(**match)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid match: {exc}")
    channels = payload.get("channels") or []
    if not isinstance(channels, list):
        raise HTTPException(status_code=400, detail="channels must be a list")
    rid = str(payload.get("id") or "").strip() or str(_uuid.uuid4())
    storage.upsert_notification_rule(
        rule_id=rid,
        name=name,
        enabled=bool(payload.get("enabled", True)),
        match=match,
        channels=[str(c) for c in channels],
        throttle_seconds=int(payload.get("throttle_seconds", 0)),
        priority=int(payload.get("priority", 100)),
    )
    notify_router.get_notifier().reload_rules()
    return {"id": rid, "saved": True}


@router.post("/notifications/rules/{rule_id}/toggle")
def notif_rule_toggle_json(
    rule_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    storage.set_notification_rule_enabled(rule_id, enabled)
    notify_router.get_notifier().reload_rules()
    return {"id": rule_id, "enabled": enabled}


@router.post("/notifications/rules/{rule_id}/silence")
def notif_rule_silence_json(
    rule_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    hours = int(payload.get("hours", 0))
    if hours <= 0:
        storage.set_notification_rule_silence(rule_id, None)
        until = None
    else:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        storage.set_notification_rule_silence(rule_id, until)
    notify_router.get_notifier().reload_rules()
    return {"id": rule_id, "silence_until": until.isoformat() if until else None}


@router.delete("/notifications/rules/{rule_id}")
def notif_rule_delete(rule_id: str) -> dict[str, Any]:
    storage.delete_notification_rule(rule_id)
    notify_router.get_notifier().reload_rules()
    return {"id": rule_id, "deleted": True}


# --- Module cards (simple per-module routing) ------------------------------
# The card UX at /notifications/routing writes one "auto:<module>" rule per
# card into the existing notification_rules table. These endpoints wrap that
# translation so the UI never has to think in condition trees.

@router.get("/notifications/cards")
def notif_cards_list() -> dict[str, Any]:
    from .notify import routing_matrix
    channels = [
        {"id": str(c["id"]), "name": c["name"], "type": c["type"],
         "enabled": c["enabled"]}
        for c in storage.list_notification_channels()
    ]
    return {
        "cards": routing_matrix.list_cards(),
        "channels": channels,
        "thresholds": routing_matrix.THRESHOLDS,
    }


@router.post("/notifications/cards/{module}/save")
def notif_card_save(
    module: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    from .notify import routing_matrix
    enabled = bool(payload.get("enabled", True))
    channel = payload.get("channel") or None
    if channel is not None:
        channel = str(channel).strip() or None
    threshold = str(payload.get("threshold") or "high")
    try:
        card = routing_matrix.save_card(
            module=module, enabled=enabled,
            channel=channel, threshold=threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"saved": True, "card": card}


@router.post("/notifications/cards/{module}/silence")
def notif_card_silence(
    module: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    from .notify import routing_matrix
    hours = int(payload.get("hours", 0))
    try:
        card = routing_matrix.silence_card(module=module, hours=hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"card": card}


@router.post("/notifications/cards/{module}/test")
def notif_card_test(module: str) -> dict[str, Any]:
    from .notify import routing_matrix
    return routing_matrix.test_card(module)


# --- Notification log ------------------------------------------------------

@router.get("/notifications/log")
def notif_log_list(
    status: str | None = None,
    channel: str | None = None,
    rule: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    entries = storage.list_notification_log(
        status=status or None,
        channel_name=channel or None,
        rule_name=rule or None,
        limit=limit,
    )
    out = []
    for e in entries:
        out.append({
            **e,
            "ts": e["ts"].isoformat() if e.get("ts") else None,
        })
    return {"count": len(out), "entries": out}


# --- Acks ------------------------------------------------------------------

@router.get("/notifications/acks")
def notif_acks_list() -> dict[str, Any]:
    rows = storage.list_notification_acks()
    out = []
    for a in rows:
        out.append({
            "fingerprint": a["fingerprint"],
            "ack_until": a["ack_until"].isoformat() if a.get("ack_until") else None,
            "reason": a.get("reason"),
            "created_at": a["created_at"].isoformat() if a.get("created_at") else None,
        })
    return {"count": len(out), "acks": out}


@router.post("/notifications/acks")
def notif_ack_add(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    fingerprint = str(payload.get("fingerprint", "")).strip()
    if not fingerprint:
        raise HTTPException(status_code=400, detail="fingerprint required")
    hours = int(payload.get("hours", 4))
    if hours <= 0:
        storage.remove_notification_ack(fingerprint)
        return {"fingerprint": fingerprint, "cleared": True}
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    storage.add_notification_ack(
        fingerprint, until, reason=(payload.get("reason") or None),
    )
    return {"fingerprint": fingerprint, "ack_until": until.isoformat()}


@router.delete("/notifications/acks/{fingerprint}")
def notif_ack_delete(fingerprint: str) -> dict[str, Any]:
    storage.remove_notification_ack(fingerprint)
    return {"fingerprint": fingerprint, "cleared": True}


# --- Live ping (drives the navbar live counter) ----------------------------

@router.get("/live/ping")
def live_ping() -> dict[str, Any]:
    """Lightweight poll target for the navbar live indicator. Returns events
    per second over the last 60 seconds. Cheap query — runs every few seconds
    from every open dashboard tab."""
    now = datetime.now(timezone.utc)
    count = storage.event_count_since(now - timedelta(seconds=60))
    return {
        "ts": now.isoformat(),
        "events_last_60s": count,
        "eps": round(count / 60.0, 2),
    }


@router.get("/modules")
def list_modules() -> dict[str, Any]:
    return {
        "registered_adapters": registry.registered_modules(),
        "token_modules": sorted(set(settings.token_module_map.values())),
    }


# ---------- RDS module endpoints -------------------------------------------

def _session_out(s: dict[str, Any], now: datetime) -> dict[str, Any]:
    connected = s["connected_at"]
    disconnected = s.get("disconnected_at")
    if disconnected:
        duration = s.get("duration_seconds") or int((disconnected - connected).total_seconds())
    else:
        duration = int((now - connected).total_seconds())
    return {
        "session_id": s["session_id"],
        "db_instance": s["db_instance"],
        "source_type": s["source_type"],
        "db_user": s.get("db_user"),
        "db_name": s.get("db_name"),
        "source_ip": s.get("source_ip"),
        "source_port": s.get("source_port"),
        "connected_at": connected.isoformat() if connected else None,
        "disconnected_at": disconnected.isoformat() if disconnected else None,
        "duration_seconds": duration,
        "active": disconnected is None,
    }


@router.get("/rds/summary")
def rds_summary() -> dict[str, Any]:
    """Overview: DBs we know about + counts of active sessions + recent auth
    failures per DB. This is what the /rds page's header renders."""
    now = datetime.now(timezone.utc)
    dbs = storage.list_rds_db_instances()
    # Auth failures in the last 24h, grouped per DB.
    since = now - timedelta(hours=24)
    fails = storage.query_events(module="aws.rds", action="rds.auth.failure",
                                  since=since, limit=500)
    fails_per_db: dict[str, int] = {}
    for f in fails:
        # query_events returns the envelope, so target is nested.
        db = ((f.get("extra") or {}).get("db_instance")
              or (f.get("target") or {}).get("id")
              or "unknown")
        fails_per_db[db] = fails_per_db.get(db, 0) + 1
    for row in dbs:
        row["last_activity"] = row["last_activity"].isoformat() if row.get("last_activity") else None
        row["auth_failures_24h"] = fails_per_db.get(row["db_instance"], 0)
    return {"databases": dbs, "auth_failures_24h_total": len(fails)}


@router.get("/rds/live")
def rds_live(db: str | None = Query(default=None)) -> dict[str, Any]:
    """Currently-connected DB sessions. Optional ?db= to filter."""
    now = datetime.now(timezone.utc)
    rows = storage.list_rds_active_sessions(db_instance=db, limit=1000)
    return {
        "count": len(rows),
        "sessions": [_session_out(r, now) for r in rows],
    }


@router.get("/rds/sessions")
def rds_sessions(
    db: str | None = Query(default=None),
    user: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    """Session history including closed ones."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    rows = storage.list_rds_recent_sessions(
        db_instance=db, db_user=user, since=since, limit=limit,
    )
    return {
        "count": len(rows),
        "hours": hours,
        "sessions": [_session_out(r, now) for r in rows],
    }


@router.get("/rds/auth-failures")
def rds_auth_failures(
    db: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    """Recent auth failure events. Optional filter by DB.

    query_events returns the stored `envelope` (a JSON blob), so all fields
    are nested (actor.principal, target.id) and event_time is already a
    string. Don't try to call datetime methods on it."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = storage.query_events(
        module="aws.rds", action="rds.auth.failure",
        since=since, limit=limit,
    )
    if db:
        rows = [r for r in rows
                if ((r.get("extra") or {}).get("db_instance")
                    or (r.get("target") or {}).get("id")) == db]
    out = []
    for r in rows:
        extra = r.get("extra") or {}
        actor = r.get("actor") or {}
        target = r.get("target") or {}
        out.append({
            "event_id": r.get("event_id"),
            "event_time": r.get("event_time"),      # already ISO-string in envelope
            "db_instance": extra.get("db_instance") or target.get("id"),
            "source_type": extra.get("source_type"),
            "user": extra.get("user") or actor.get("principal"),
            "source_ip": extra.get("source_ip") or actor.get("source_ip"),
            "reason": extra.get("reason"),
            "message": extra.get("message"),
        })
    return {"count": len(out), "hours": hours, "failures": out}


