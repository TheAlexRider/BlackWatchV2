"""HTTP surface: ingest + search. Transport lives here; it knows nothing about
event meaning beyond authenticating the source and routing to its module."""

from __future__ import annotations

import uuid
import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Query, Request, Response

from .auth import require_role
from pydantic import BaseModel

from . import auth, coverage, investigation_flow, noise, storage
from .intel import db as intel_db
from .intel import enrich as intel_enrich
from .connectors import operations as connector_operations
from .connectors import runner as connector_runner
from .config import settings
from .notify import router as notify_router
from .pipeline import NormalizationError, ingest_payload
from .rules import engine as rule_engine
from .rules.model import Condition

router = APIRouter()


class InvestigationCreate(BaseModel):
    ip: str
    title: str | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    time_start: datetime | None = None
    time_end: datetime | None = None


class InvestigationNoteCreate(BaseModel):
    body: str


class InvestigationStatusUpdate(BaseModel):
    status: Literal[
        "ready", "investigating", "contained", "confirmed_malicious",
        "confirmed_expected", "false_positive", "inconclusive", "closed",
    ]


def _current_user(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return str(user)


def _owned_investigation(request: Request, investigation_id: str) -> tuple[uuid.UUID, dict[str, Any]]:
    try:
        parsed = uuid.UUID(investigation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid investigation id") from exc
    row = storage.get_investigation(parsed)
    if not row or row["owner"] != _current_user(request):
        raise HTTPException(status_code=404, detail="investigation not found")
    return parsed, row


# ---------- Auth --------------------------------------------------------------

@router.post("/auth/login")
def auth_login(
    response: Response,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Verify credentials and set the session cookie."""
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")
    user = storage.get_user(username)
    if user is None or not auth.verify_password(password, user["password_hash"]):
        # Same detail whether user or password wrong — no enumeration.
        raise HTTPException(status_code=401, detail="invalid credentials")
    sid, expires = auth.create_session(username)
    # HttpOnly + SameSite=Lax so the cookie can ride redirects from /login
    # → next but isn't scriptable. Secure flag is left off for the HTTP-only
    # dev deploy; enable via a reverse proxy when TLS terminates upstream.
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=sid,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "username": username,
            "expires_at": expires.isoformat()}


@router.post("/auth/logout")
def auth_logout(
    response: Response,
    bw_session: str | None = Cookie(default=None, alias="bw_session"),
) -> dict[str, Any]:
    """Invalidate the session (best-effort) and clear the cookie."""
    auth.delete_session(bw_session)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    """Whoami. Returns 401 via the middleware if no valid session."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    role = getattr(request.state, "role", None) or storage.get_user_role(user)
    return {"username": user, "role": role}


@router.get("/whoami")
def whoami(request: Request) -> dict[str, Any]:
    """UI-friendly alias for /auth/me. Returns {user, role}."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    role = getattr(request.state, "role", None) or storage.get_user_role(user)
    return {"user": user, "role": role}


@router.get("/audit")
def audit_list(
    request: Request,
    _: tuple[str, str] = Depends(require_role("admin")),
    limit: int = Query(200, ge=1, le=1000),
    actor: str | None = Query(default=None),
    since: str | None = Query(default=None),
    path: str | None = Query(default=None),
) -> dict[str, Any]:
    """Paginated audit log. Admin-only."""
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid since")
    rows = storage.list_audit(
        limit=limit, actor=actor, since=since_dt, path_like=path,
    )
    return {
        "rows": [
            {
                **r,
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else r["ts"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/auth/change-password")
def auth_change_password(
    request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Change the current user's password. Requires re-verifying the
    current password so cookie theft alone can't rotate the credential."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    current = str(payload.get("current_password") or "")
    new = str(payload.get("new_password") or "")
    if not current or not new:
        raise HTTPException(
            status_code=400, detail="current_password and new_password required",
        )
    ok, msg = auth.change_password(user, current, new)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


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


@router.get("/events/options")
def event_filter_options() -> dict[str, list[str]]:
    """Return selectable values for the Events filter bar.

    The values come from stored events, so the UI never invents provider
    names. A bounded read keeps this endpoint cheap on large installations.
    """
    events = storage.query_events(limit=5000)
    categories: set[str] = set()
    modules: set[str] = set()
    actions: set[str] = set()
    severities: set[str] = set()
    for event in events:
        for value, bucket in (
            (event.get("category"), categories),
            ((event.get("source") or {}).get("module"), modules),
            (event.get("action"), actions),
            (event.get("severity"), severities),
        ):
            if value:
                bucket.add(str(value))
    return {
        "categories": sorted(categories),
        "modules": sorted(modules),
        "actions": sorted(actions),
        "severities": sorted(severities),
    }


# ---------- Investigations --------------------------------------------------

@router.get("/investigations")
def investigations_list(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    return {"investigations": storage.list_investigations(owner=user)}


@router.post("/investigations", status_code=201)
def investigations_create(request: Request, payload: InvestigationCreate) -> dict[str, Any]:
    user = _current_user(request)
    try:
        ip = str(ipaddress.ip_address(payload.ip.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ip must be a valid IPv4 or IPv6 address") from exc
    now = datetime.now(timezone.utc)
    start = payload.time_start or (now - timedelta(days=30))
    end = payload.time_end or now
    if end < start or (end - start).days > 365:
        raise HTTPException(status_code=400, detail="time range must be valid and no longer than 365 days")
    title = (payload.title or f"Investigate {ip}").strip()[:160]
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    investigation_id = uuid.uuid4()
    row = storage.create_investigation(
        investigation_id=investigation_id, title=title, owner=user,
        time_start=start, time_end=end, priority=payload.priority,
        observable_value=ip,
    )
    return investigation_flow.create_initial_scan(
        storage,
        investigation_id=investigation_id,
        requested_by=user,
        row=row,
    )


@router.get("/investigations/{investigation_id}")
def investigations_get(request: Request, investigation_id: str) -> dict[str, Any]:
    parsed, row = _owned_investigation(request, investigation_id)
    return {
        **row,
        "notes": storage.list_investigation_notes(parsed),
        "results": storage.list_investigation_results(parsed),
        "scan": storage.get_active_investigation_scan(parsed),
    }


@router.post("/investigations/{investigation_id}/scan", status_code=202)
def investigations_scan(request: Request, investigation_id: str) -> dict[str, Any]:
    parsed, row = _owned_investigation(request, investigation_id)
    if row["status"] == "closed":
        raise HTTPException(status_code=409, detail="closed investigations cannot be scanned")
    observable = next((value.split(":", 1)[1] for value in row["observables"] if value.startswith("ip:")), None)
    if not observable:
        raise HTTPException(status_code=400, detail="investigation has no IP observable")
    storage.update_investigation_status(parsed, "investigating")
    scan = storage.create_investigation_scan(scan_id=uuid.uuid4(), investigation_id=parsed, requested_by=_current_user(request))
    return {"status": scan["status"], "scan_id": scan["id"], "investigation": storage.get_investigation(parsed)}


class InvestigationRangeUpdate(BaseModel):
    time_start: datetime
    time_end: datetime


@router.patch("/investigations/{investigation_id}/range")
def investigations_range(request: Request, investigation_id: str, payload: InvestigationRangeUpdate) -> dict[str, Any]:
    parsed, _ = _owned_investigation(request, investigation_id)
    start = payload.time_start
    end = payload.time_end
    if end < start or (end - start).days > 365:
        raise HTTPException(status_code=400, detail="time range must be valid and no longer than 365 days")
    storage.update_investigation_range(parsed, start, end)
    return storage.get_investigation(parsed) or {}


@router.post("/investigations/{investigation_id}/notes", status_code=201)
def investigations_note(
    request: Request, investigation_id: str, payload: InvestigationNoteCreate,
) -> dict[str, Any]:
    parsed, row = _owned_investigation(request, investigation_id)
    body = payload.body.strip()
    if not body or len(body) > 10000:
        raise HTTPException(status_code=400, detail="note must be between 1 and 10000 characters")
    return storage.add_investigation_note(parsed, row["owner"], body)


@router.patch("/investigations/{investigation_id}/status")
def investigations_status(
    request: Request, investigation_id: str, payload: InvestigationStatusUpdate,
) -> dict[str, Any]:
    parsed, _ = _owned_investigation(request, investigation_id)
    storage.update_investigation_status(parsed, payload.status)
    return storage.get_investigation(parsed) or {}


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
                "description": r.description,
                "enabled": r.enabled,
                "rule_action": r.action,        # "alert" | "suppress"
                "matched_actions": rule_engine.extract_matched_actions(r.match),
                "severity": r.severity.value if r.severity else None,
                "tags": r.tags,
            }
            for r in rules
        ],
        # Full mute rows (id + all filters + note + created_at). The UI
        # renders id-driven unmute buttons and shows the filter columns so
        # the operator can see which specific combo is silenced.
        "muted": storage.list_muted_events(),
    }


@router.post("/rules/{rule_id}/toggle", dependencies=[Depends(require_role("admin"))])
def rule_toggle(rule_id: str, enabled: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Toggle a single rule on or off. Persists the override and updates the
    live engine in-process."""
    storage.set_rule_override(rule_id, enabled)
    rule_engine.get_engine().set_enabled(rule_id, enabled)
    return {"rule_id": rule_id, "enabled": enabled}


_ALLOWED_SEVERITIES = {"informational", "low", "medium", "high", "critical"}


@router.post("/rules/{rule_id}/severity", dependencies=[Depends(require_role("admin"))])
def rule_severity(
    rule_id: str,
    severity: str | None = Body(None, embed=True),
) -> dict[str, Any]:
    """Override a rule's severity. Passing null clears the override and
    the rule falls back to whatever the YAML defines."""
    if severity is not None and severity not in _ALLOWED_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"severity must be one of {sorted(_ALLOWED_SEVERITIES)} or null",
        )
    storage.set_rule_severity_override(rule_id, severity)
    from .event import Severity
    sev_obj = Severity(severity) if severity else None
    rule_engine.get_engine().set_severity(rule_id, sev_obj)
    return {"rule_id": rule_id, "severity": severity}


class _MuteAdd(BaseModel):
    action: str
    source_type: str | None = None
    username: str | None = None
    reason: str | None = None
    note: str | None = None


@router.post("/noise/mute", dependencies=[Depends(require_role("admin"))])
def noise_mute(body: _MuteAdd) -> dict[str, Any]:
    """Add a mute rule. Only `action` is required; source_type / username /
    reason narrow the mute to a specific combo (all optional, NULL matches
    any). Note: this stops events from being stored/scored/notified but
    does NOT reduce AWS cost — see EventBridge pattern in deploy/iam/."""

    def _clean(s: str | None) -> str | None:
        s = (s or "").strip()
        return s or None

    action = _clean(body.action)
    if not action:
        raise HTTPException(status_code=400, detail="action required")
    mute_id = storage.add_muted_event(
        action,
        source_type=_clean(body.source_type),
        username=_clean(body.username),
        reason=_clean(body.reason),
        note=_clean(body.note),
    )
    noise.refresh()
    return {"id": mute_id, "action": action, "muted": True}


@router.post("/noise/unmute", dependencies=[Depends(require_role("admin"))])
def noise_unmute(id: int = Body(..., embed=True)) -> dict[str, Any]:
    storage.remove_muted_event(id)
    noise.refresh()
    return {"id": id, "muted": False}


class ModulesRefreshBody(BaseModel):
    """Body of POST /modules/refresh — a small set of connector types to
    drain synchronously on demand. Used by the Refresh button on each
    module page (/api-gw, /rds, /iam, /vpn) so the operator can pull the
    freshest events without waiting for the scheduler poll interval."""
    connector_types: list[str]


class ConnectorRunBody(BaseModel):
    kind: Literal["manual", "test"] = "manual"


class RetryAllBody(BaseModel):
    scope: Literal["eligible", "all"] = "eligible"


@router.post("/modules/refresh", dependencies=[Depends(require_role("admin"))])
def modules_refresh(body: ModulesRefreshBody) -> dict[str, Any]:
    """Trigger a one-shot run of every enabled connector whose type is in
    the request. Returns per-connector outcome plus the aggregate
    ingested count so the UI can show a toast."""
    wanted = {t for t in body.connector_types if isinstance(t, str) and t}
    if not wanted:
        return {"ran": [], "total_ingested": 0}
    ran: list[dict[str, Any]] = []
    total = 0
    for c in storage.list_connectors():
        if c["type"] not in wanted or not c.get("enabled"):
            continue
        result = connector_runner.run_connector(c["id"])
        ingested = result.get("ingested")
        ran.append({
            "connector_id": c["id"],
            "connector_name": c.get("name"),
            "type": c["type"],
            "status": result.get("status"),
            "ingested": ingested if isinstance(ingested, int) else 0,
            "error": result.get("error"),
        })
        if isinstance(ingested, int):
            total += ingested
    return {"ran": ran, "total_ingested": total}


@router.get("/connectors")
def connectors_list() -> dict[str, Any]:
    """All configured connectors with their schedule/status. The Next.js UI
    renders this at /connectors with Test / Run / Toggle / Delete actions."""
    rows = storage.list_connectors()
    latest = connector_operations.get_latest_connector_operations([r["id"] for r in rows])
    out = []
    for r in rows:
        operation = latest.get(r["id"])
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
            "retry_count": r.get("retry_count", 0),
            "next_attempt_at": r.get("next_attempt_at").isoformat()
            if r.get("next_attempt_at") else None,
            "scheduler_reason": r.get("scheduler_reason"),
            "health_state": _connector_health_state(r, operation),
            "latest_operation": connector_operations.serialize_operation(operation),
        })
    scheduler = storage.get_connector_scheduler_state()
    return {
        "count": len(out), "connectors": out,
        "scheduler": {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in (scheduler or {}).items()
        },
    }


def _connector_health_state(
    connector: dict[str, Any], operation: dict[str, Any] | None,
) -> str:
    from .connectors.scheduler import connector_health_state

    row = dict(connector)
    row["operation_status"] = operation.get("status") if operation else None
    return connector_health_state(row)


@router.post("/connectors/{connector_id}/run", status_code=202,
             dependencies=[Depends(require_role("admin"))])
def connector_run_now(
    connector_id: str,
    body: ConnectorRunBody | None = None,
    actor: tuple[str, str] = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = connector_operations.start_connector_operation(
        connector_id,
        kind=(body.kind if body else "manual"),
        created_by=actor[0],
    )
    if result.get("status") == "rejected" and result.get("error") == "connector not found":
        raise HTTPException(status_code=404, detail="connector not found")
    return result


@router.post("/connectors/{connector_id}/test", status_code=202,
             dependencies=[Depends(require_role("admin"))])
def connector_test_now(
    connector_id: str,
    actor: tuple[str, str] = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = connector_operations.start_connector_operation(
        connector_id, kind="test", created_by=actor[0],
    )
    if result.get("status") == "rejected" and result.get("error") == "connector not found":
        raise HTTPException(status_code=404, detail="connector not found")
    return result


@router.get("/connector-operations/{operation_id}")
def connector_operation_get(operation_id: str) -> dict[str, Any]:
    result = connector_operations.operation_details(operation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="operation not found")
    return result


@router.post("/connectors/retry-all", status_code=202,
             dependencies=[Depends(require_role("admin"))])
def connectors_retry_all(
    body: RetryAllBody | None = None,
    actor: tuple[str, str] = Depends(require_role("admin")),
) -> dict[str, Any]:
    return connector_operations.start_retry_all(
        scope=body.scope if body else "eligible", created_by=actor[0],
    )


@router.get("/connectors/scheduler")
def connectors_scheduler_status() -> dict[str, Any]:
    state = storage.get_connector_scheduler_state()
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in (state or {}).items()
    }


@router.get("/coverage")
def coverage_view() -> dict[str, Any]:
    """Return a compact, read-only view of collector coverage and freshness."""
    return coverage.build_coverage_summary(storage.list_connectors())


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


@router.delete("/vpn/servers/{server}", dependencies=[Depends(require_role("admin"))])
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
            "display_name": row.get("display_name"),
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


@router.get("/hosts/{instance_id}/metrics")
def host_metrics_hourly(
    instance_id: str,
    hours: int = Query(default=48, ge=1, le=336),  # cap at 14-day retention
) -> dict[str, Any]:
    """Hourly rollup of memory / CPU / disk %. Used by the host detail
    page's chart. Each row has min/avg/max per metric — draws as a band
    with an avg line, CloudWatch-style. Returns oldest-first for direct
    left-to-right chart rendering."""
    rows = storage.list_host_metrics_hourly(instance_id, hours=hours)
    return {
        "instance_id": instance_id,
        "hours": hours,
        "count": len(rows),
        "series": rows,
    }


@router.put("/hosts/{instance_id}/display-name", dependencies=[Depends(require_role("admin"))])
def host_set_display_name(
    instance_id: str, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Set the user-editable friendly name for a host. Empty or missing
    display_name clears it (falls back to hostname > instance_id in the UI).
    Returns 404 if the host has never reported."""
    if storage.get_host_status(instance_id) is None:
        raise HTTPException(status_code=404, detail="host not found")
    name = payload.get("display_name")
    if name is not None and not isinstance(name, str):
        raise HTTPException(status_code=400, detail="display_name must be a string")
    storage.set_host_display_name(instance_id, name)
    return {"instance_id": instance_id, "display_name": (name or "").strip() or None}


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

_VALID_PERF_METRICS = {
    "memory_pct",
    "cpu_utilization_pct",
    "disk_pct_max",
}
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
            "display_name": h.get("display_name"),
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


def _perf_scope_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract scope-related fields from an incoming payload, normalising
    empty strings/arrays to None/[]. Precedence matches
    perf_alerts._rule_targets_instance."""
    raw_ids = payload.get("instance_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    ids = [str(x).strip() for x in raw_ids if str(x).strip()]
    return {
        "instance_id": (payload.get("instance_id") or None),
        "tag_key": (payload.get("tag_key") or None),
        "tag_value": (payload.get("tag_value") or None),
        "instance_ids": ids,
    }


@router.post("/perf-alerts", dependencies=[Depends(require_role("admin"))])
def perf_alerts_create(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a new perf alert rule. Validation is permissive on display
    fields (name, severity), strict on semantic fields (metric, scope)."""
    rule_id = payload.get("id") or str(__import__("uuid").uuid4())
    _validate_perf_payload(payload)
    scope = _perf_scope_fields(payload)
    storage.upsert_perf_alert_rule(
        rule_id,
        name=str(payload["name"]).strip(),
        enabled=bool(payload.get("enabled", True)),
        module=payload.get("module") or "ec2.host",
        instance_id=scope["instance_id"],
        tag_key=scope["tag_key"],
        tag_value=scope["tag_value"],
        instance_ids=scope["instance_ids"],
        metric=payload["metric"],
        comparison=payload.get("comparison", "gte"),
        threshold=float(payload["threshold"]),
        window_seconds=int(payload.get("window_seconds", 300)),
        min_breach_ratio=float(payload.get("min_breach_ratio", 0.6)),
        severity=payload.get("severity", "high"),
        channels=list(payload.get("channels") or []),
        throttle_seconds=int(payload.get("throttle_seconds", 1800)),
        message_template=(payload.get("message_template") or None),
    )
    return {"id": rule_id}


@router.put("/perf-alerts/{rule_id}", dependencies=[Depends(require_role("admin"))])
def perf_alerts_update(
    rule_id: str, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    if storage.get_perf_alert_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail="rule not found")
    _validate_perf_payload(payload)
    scope = _perf_scope_fields(payload)
    storage.upsert_perf_alert_rule(
        rule_id,
        name=str(payload["name"]).strip(),
        enabled=bool(payload.get("enabled", True)),
        module=payload.get("module") or "ec2.host",
        instance_id=scope["instance_id"],
        tag_key=scope["tag_key"],
        tag_value=scope["tag_value"],
        instance_ids=scope["instance_ids"],
        metric=payload["metric"],
        comparison=payload.get("comparison", "gte"),
        threshold=float(payload["threshold"]),
        window_seconds=int(payload.get("window_seconds", 300)),
        min_breach_ratio=float(payload.get("min_breach_ratio", 0.6)),
        severity=payload.get("severity", "high"),
        channels=list(payload.get("channels") or []),
        throttle_seconds=int(payload.get("throttle_seconds", 1800)),
        message_template=(payload.get("message_template") or None),
    )
    return {"id": rule_id}


@router.delete("/perf-alerts/{rule_id}", dependencies=[Depends(require_role("admin"))])
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
    "cpu_utilization_pct": {
        "label": "CPU utilization %",
        "blurb": "True /proc/stat-based utilization, 0-100%. Matches CloudWatch.",
        "default_threshold": 85,
        "default_window_minutes": 5,
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


@router.post("/notifications/perf-alerts/quick", dependencies=[Depends(require_role("admin"))])
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
    # Scope options (matches perf_alerts._rule_targets_instance):
    #   instance_ids: multi-instance                (non-empty JSON list)
    #   instance_id : single specific instance     (legacy single-instance)
    #   tag_key/value: tag-matched fleet
    #   scope=all   : matches every host           (opt-in via explicit flag)
    # Only one scope may be set at a time. "all" requires no other fields.
    scope_flag = str(p.get("scope") or "").lower()
    has_instance = bool(p.get("instance_id"))
    has_tag = bool(p.get("tag_key")) and p.get("tag_value") is not None
    ids = p.get("instance_ids") or []
    has_ids = bool(ids) if isinstance(ids, list) else False
    is_all = scope_flag == "all"

    active = [n for n, v in (
        ("instance", has_instance),
        ("tag", has_tag),
        ("instance_ids", has_ids),
        ("all", is_all),
    ) if v]
    if len(active) == 0:
        raise HTTPException(
            status_code=400,
            detail="scope required: instance_id, instance_ids, tag_key+tag_value, or scope=all",
        )
    if len(active) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"scope conflict: pick one — got {active}",
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


@router.post("/notifications/test", dependencies=[Depends(require_role("admin"))])
def test_notification(channel: str) -> dict[str, Any]:
    return notify_router.get_notifier().send_test(channel)


# ---------- Notifications (DB-backed) — list / read / save / mutate ---------
# Mutation endpoints accept JSON bodies so the Next.js UI can ship per-type
# channel config dicts and Condition trees without a YAML textarea.

# ---------- Notification Studio (module + alert kind) -----------------------

@router.get("/notifications/profiles")
def notif_profiles_list() -> dict[str, Any]:
    from .notify import profile_service, profiles as profile_model
    channels = [
        {"id": str(c["id"]), "name": c["name"], "type": c["type"],
         "enabled": c["enabled"]}
        for c in storage.list_notification_channels()
    ]
    return {
        "profiles": profile_service.list_profiles(),
        "catalog": profile_model.NOTIFICATION_CATALOG,
        "channels": channels,
    }


@router.post("/notifications/profiles/preview", dependencies=[Depends(require_role("admin"))])
def notif_profile_preview(
    channel_type: str = "slack",
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    from .notify import profile_service
    try:
        return {"rendered": profile_service.render_preview(payload, channel_type)}
    except (TypeError, ValueError) as exc:
        storage.record_notification_profile_audit(
            str(payload.get("id") or "preview"),
            "preview_error",
            str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/notifications/profiles/save", dependencies=[Depends(require_role("admin"))])
def notif_profile_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .notify import profile_service
    try:
        return {"saved": True, "profile": profile_service.save_profile(payload)}
    except (TypeError, ValueError) as exc:
        storage.record_notification_profile_audit(
            str(payload.get("id") or "unknown"),
            "save_error",
            str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/notifications/profiles/{profile_id}", dependencies=[Depends(require_role("admin"))])
def notif_profile_delete(profile_id: str) -> dict[str, Any]:
    from .notify import profile_service
    profile_service.delete_profile(profile_id)
    return {"deleted": True, "id": profile_id}


@router.post("/notifications/profiles/{profile_id}/test", dependencies=[Depends(require_role("admin"))])
def notif_profile_test(profile_id: str) -> dict[str, Any]:
    from .notify import profile_service
    return profile_service.test_profile(profile_id)

@router.get("/notifications/templates/recent-events")
def notif_recent_events(
    module: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Real recent events for template preview. Lets the operator render
    their template against actual traffic — closer to CloudWatch Logs
    Insights' "test pattern against sample records" flow than a hand-crafted
    sample. Newest first."""
    events = storage.query_events(module=module or None, limit=limit)
    out = []
    for env in events:
        # Envelope shape: event_id, event_time, action, severity, actor, target...
        actor = env.get("actor") or {}
        target = env.get("target") or {}
        source = env.get("source") or {}
        out.append({
            "event_id": env.get("event_id"),
            "event_time": env.get("event_time"),
            "action": env.get("action"),
            "severity": env.get("severity"),
            "module": source.get("module"),
            "principal": actor.get("principal"),
            "target_name": target.get("name") or target.get("id"),
        })
    return {"count": len(out), "events": out}


@router.get("/notifications/templates")
def notif_templates(
    channel_type: str | None = None,
    context_kind: str | None = None,
) -> dict[str, Any]:
    """Named message templates per channel type. Powers the UI's template
    picker so users can choose a friendly layout instead of writing Jinja by
    hand.

    context_kind=perf returns perf-alert flavored presets (flat context:
    hostname, metric_label, threshold, current_value, …) instead of the
    default event-shaped presets. Perf rules render their template with
    flat vars before the channel wraps it."""
    from .notify.channels import TEMPLATE_PRESETS, PERF_TEMPLATE_PRESETS
    presets_by_type = (
        PERF_TEMPLATE_PRESETS if (context_kind or "").lower() == "perf" else TEMPLATE_PRESETS
    )
    if channel_type:
        return {"type": channel_type, "presets": presets_by_type.get(channel_type, [])}
    return {"presets_by_type": presets_by_type}


# Baseline flat context used to preview perf-alert templates. The wizard
# overlays the current form state on top of this via payload["perf_context"]
# so the preview reflects the metric/threshold/window the operator is
# actually configuring — not a stale CPU sample.
_PERF_PREVIEW_CTX_DEFAULTS: dict[str, Any] = {
    "instance_id": "i-03499c8ce39a70d21",
    "hostname": "ip-172-16-1-97",
    "metric": "cpu_utilization_pct",
    "metric_label": "CPU utilization",
    "threshold": 80,
    "comparison": "gte",
    "current_value": 98.0,
    "window_seconds": 300,
    "window_minutes": 5,
    "rule_name": "CPU utilization ≥ 80% on prod for 5 minutes",
    "severity": "high",
    "tags": {"env": "Mgmt", "role": "Mgmt-NAT"},
}


def _build_perf_preview_ctx(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge the wizard's `perf_context` override onto the defaults. Missing
    keys keep their defaults so a partially-filled form still previews.
    Also fabricates a plausible `current_value` if the caller left it unset:
    for `gte/gt` we set it 15pp above the threshold (capped at 100); for
    `lte/lt` we set it 15pp below (floored at 0)."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    ctx = dict(_PERF_PREVIEW_CTX_DEFAULTS)
    override = payload.get("perf_context") or {}
    if isinstance(override, dict):
        for k, v in override.items():
            if v is None:
                continue
            ctx[k] = v

    # window_seconds derived from window_minutes when the wizard sends the
    # minutes value (which is what the UI actually tracks).
    if "window_minutes" in ctx:
        try:
            wm = int(ctx["window_minutes"])
            ctx["window_seconds"] = max(60, wm * 60)
        except (TypeError, ValueError):
            pass

    # Plausible current_value derived from threshold + comparison. Only if
    # the caller didn't already send one.
    if "current_value" not in (override or {}):
        try:
            thr = float(ctx.get("threshold", 80))
            comp = str(ctx.get("comparison") or "gte").lower()
            if comp in ("gte", "gt"):
                ctx["current_value"] = min(100.0, round(thr + 15.0, 1))
            elif comp in ("lte", "lt"):
                ctx["current_value"] = max(0.0, round(thr - 15.0, 1))
        except (TypeError, ValueError):
            pass

    # Fabricate a rule_name so `{{ rule_name }}` in templates doesn't render
    # the stale CPU-flavored default when the operator's picked memory/disk.
    if "rule_name" not in (override or {}):
        try:
            op = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<"}[str(ctx["comparison"])]
        except (KeyError, TypeError):
            op = "≥"
        ctx["rule_name"] = (
            f"{ctx.get('metric_label', ctx.get('metric', 'metric'))} "
            f"{op} {ctx.get('threshold', '?')}% "
            f"for {ctx.get('window_minutes', '?')}m"
        )

    # Timestamp bundle — mirrors the fire-time context in perf_alerts.
    # "Now" for the preview so operators see how a fresh alert would render.
    now = _dt.now(_tz.utc)
    try:
        wm = int(ctx.get("window_minutes") or 5)
    except (TypeError, ValueError):
        wm = 5
    window_end = now.replace(second=0, microsecond=0)
    window_start = window_end - _td(minutes=max(1, wm))
    ctx["fired_at"] = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    ctx["window_start"] = window_start.strftime("%Y-%m-%d %H:%M UTC")
    ctx["window_end"] = window_end.strftime("%Y-%m-%d %H:%M UTC")
    ctx["window_range"] = (
        f"{window_start.strftime('%H:%M')}–{window_end.strftime('%H:%M')} UTC"
    )
    ctx["event_time"] = now.isoformat()

    return ctx


def _render_preview(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Shared render logic for preview + test-preview.
    Returns (rendered_body, error_string_or_None).

    Handles both event-shape templates (default) and perf flat-context
    templates (context_kind=perf). Perf mode does a two-pass render:
      1. user's template with flat perf vars → the message line
      2. channel type's default template with event.extra.message set to
         that line → the final body the channel would deliver
    That way the preview matches what actually arrives in Slack/Discord/etc.
    """
    from jinja2 import ChainableUndefined, Environment
    from .notify import channels as channels_module

    import logging
    import traceback

    channel_type = str(payload.get("channel_type") or "slack").lower()
    context_kind = str(payload.get("context_kind") or "event").lower()
    template = str(payload.get("template") or "").strip()

    if not template:
        if context_kind == "perf":
            perf_presets = channels_module.PERF_TEMPLATE_PRESETS.get(channel_type) or []
            template = perf_presets[0]["template"] if perf_presets else ""
        else:
            template = channels_module._DEFAULT_TEMPLATES.get(channel_type) or ""
    if not template:
        return "", None

    sample_kind = str(payload.get("sample_event") or ("perf_alert" if context_kind == "perf" else "vpn_failure")).lower()

    try:
        env = Environment(autoescape=False, undefined=ChainableUndefined, trim_blocks=True)

        if context_kind == "perf":
            # Merge the wizard's live form state onto the sample so the
            # preview reflects what the operator's actually building.
            perf_ctx = _build_perf_preview_ctx(payload)
            # Pass 1: render the user's perf template with flat context.
            intermediate = env.from_string(template).render(**perf_ctx)
            # Pass 2: wrap it in the channel type's default template so the
            # preview shows the final message the operator actually receives.
            sample = _build_preview_sample("perf_alert", payload)
            sample_dict = sample.model_dump(mode="json")
            # Also patch the event.extra fields so channel templates that
            # reference event.severity / event.target.name / event.extra.tags
            # honor the wizard's current picks (severity, hostname, tags).
            sample_dict["severity"] = str(perf_ctx.get("severity", sample_dict.get("severity")))
            extra = sample_dict.setdefault("extra", {})
            extra["message"] = intermediate
            extra["metric"] = perf_ctx.get("metric", extra.get("metric"))
            extra["metric_label"] = perf_ctx.get("metric_label", extra.get("metric_label"))
            extra["threshold"] = perf_ctx.get("threshold", extra.get("threshold"))
            extra["current_value"] = perf_ctx.get("current_value", extra.get("current_value"))
            extra["window_seconds"] = perf_ctx.get("window_seconds", extra.get("window_seconds"))
            extra["rule_name"] = perf_ctx.get("rule_name", extra.get("rule_name"))
            if perf_ctx.get("tags"):
                extra["tags"] = perf_ctx["tags"]
            target = sample_dict.setdefault("target", {})
            if perf_ctx.get("hostname"):
                target["name"] = perf_ctx["hostname"]
            if perf_ctx.get("instance_id"):
                target["id"] = perf_ctx["instance_id"]
            channel_tpl = channels_module._DEFAULT_TEMPLATES.get(channel_type) or "{{ event.extra.message }}"
            rendered = env.from_string(channel_tpl).render(
                event=sample_dict,
                channel_name=str(payload.get("channel_name") or "preview"),
            )
            return rendered, None

        # Event mode (existing behavior).
        event_id = payload.get("event_id")
        if event_id:
            envelope = storage.get_event(str(event_id))
            if envelope is None:
                return "", f"event {event_id!r} not found"
            sample_dict = envelope
        else:
            sample = _build_preview_sample(sample_kind, payload)
            sample_dict = sample.model_dump(mode="json")

        rendered = env.from_string(template).render(
            event=sample_dict,
            channel_name=str(payload.get("channel_name") or "preview"),
        )
        return rendered, None
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "template preview failed: sample_kind=%s context_kind=%s",
            sample_kind, context_kind,
        )
        tb_last = traceback.format_exc().splitlines()[-1] if exc else ""
        return "", f"{exc.__class__.__name__}: {exc} — {tb_last}"


@router.post("/notifications/templates/preview", dependencies=[Depends(require_role("admin"))])
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
      context_kind   — event (default) | perf. Perf renders flat perf vars
                       through the channel's default template so the preview
                       matches what a real perf alert would deliver.
      sample_event   — perf_alert | fim_modified | ssh_failure | vpn_failure
      sample_action  — override the action name on the sample (kept for compat)
    """
    rendered, error = _render_preview(payload)
    return {"rendered": rendered, "error": error}


@router.post("/notifications/templates/test-send", dependencies=[Depends(require_role("admin"))])
def notif_template_test_send(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Render the current template against sample data and deliver it via the
    named channel. Powers the "Send test" button in the alert wizards so the
    operator can see the exact message land in Slack/Discord/etc before saving
    the rule.

    Accepts:
      channel_name  — the notification channel to deliver through (required)
      template      — Jinja source. Empty/null falls back to the channel's
                      default preset (same as preview).
      channel_type  — override for preview render (defaults to the channel's
                      configured type).
      context_kind  — event (default) | perf
      sample_event  — canned sample to render against
    """
    from .notify import channels as channels_module

    channel_name = str(payload.get("channel_name") or "").strip()
    if not channel_name:
        raise HTTPException(status_code=400, detail="channel_name required")

    notifier = notify_router.get_notifier()
    channel = notifier.channels.get(channel_name)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"unknown channel: {channel_name}")

    payload.setdefault("channel_type", channel.type)
    rendered, error = _render_preview(payload)
    if error:
        return {"channel": channel_name, "status": "render_error", "detail": error}

    # Deliver the rendered body directly through the type-specific sender so
    # we bypass the channel's default template (we've already rendered).
    sender = channels_module._SENDERS.get(channel.type)
    if sender is None:
        return {"channel": channel_name, "status": "error",
                "detail": f"unknown channel type: {channel.type}"}

    # Build a synthetic event to pass alongside the body — webhook / teams
    # senders serialize it into their payload. Perf-shape gets the perf sample;
    # event-shape gets the event sample.
    context_kind = str(payload.get("context_kind") or "event").lower()
    sample_kind = str(payload.get("sample_event") or ("perf_alert" if context_kind == "perf" else "vpn_failure")).lower()
    sample_event = _build_preview_sample(sample_kind, payload)

    ok, detail = sender(channel.resolved_config(), rendered, sample_event)
    return {
        "channel": channel_name,
        "status": "sent" if ok else "error",
        "detail": detail,
        "rendered": rendered,
    }


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
                "metric": "cpu_utilization_pct",
                "metric_label": "CPU utilization",
                "rule_id": "preview-rule-id",
                "rule_name": "CPU utilization ≥ 80% on Mgmt-NAT EC2 for 5 minutes",
                "threshold": 80,
                "comparison": "gte",
                "current_value": 98.0,
                "window_seconds": 300,
                "min_breach_ratio": 0.6,
                "message": "CPU utilization ≥ 80% for 5m (current: 98.0%)",
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

    # --- ECS probe samples ------------------------------------------------
    # Bodies mirror services/projection.py::_friendly_service_message so a
    # test-send lands in the channel looking exactly like the real thing.
    if kind == "service_down":
        return Event(
            source=Source(module="ecs.probe", transport="api", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.other,
            action=sample_action or "service.down",
            outcome=Outcome.failure,
            severity=Severity.critical,
            target=Target(id="prod/api-gateway", type="ecs.service",
                          name="api-gateway"),
            extra={
                "vpc": "prod", "name": "api-gateway", "tier": "http",
                "target_id": "prod/api-gateway",
                "prev_status": "up", "status": "down",
                "error": "Connection refused",
                "tags": {"env": "prod", "tier": "http"},
                "message": (
                    "*api-gateway went DOWN*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• *VPC:* prod\n"
                    "• *Error:* connection refused\n"
                    "• *Since:* 2026-07-17 14:30 UTC\n"
                    "• *Env:* prod"
                ),
            },
        )

    if kind == "service_degraded":
        return Event(
            source=Source(module="ecs.probe", transport="api", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.other,
            action=sample_action or "service.degraded",
            outcome=Outcome.failure,
            severity=Severity.high,
            target=Target(id="prod/checkout", type="ecs.service",
                          name="checkout"),
            extra={
                "vpc": "prod", "name": "checkout", "tier": "http",
                "target_id": "prod/checkout",
                "prev_status": "up", "status": "degraded",
                "latency_ms": 2400,
                "error": "HTTP 502",
                "tags": {"env": "prod", "tier": "http"},
                "message": (
                    "*checkout is degraded*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• *VPC:* prod\n"
                    "• *Signal:* HTTP 502\n"
                    "• *Latency:* 2400 ms\n"
                    "• *Env:* prod"
                ),
            },
        )

    if kind == "service_unknown":
        return Event(
            source=Source(module="ecs.probe", transport="api", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.other,
            action=sample_action or "service.unknown",
            outcome=Outcome.failure,
            severity=Severity.high,
            target=Target(id="prod/keycloak", type="ecs.service", name="keycloak"),
            extra={
                "vpc": "prod", "name": "keycloak", "tier": "http_alive",
                "target_id": "prod/keycloak", "status": "unknown",
                "error": "timed out", "tags": {"env": "prod", "tier": "http_alive"},
                "message": (
                    "*Unable to verify keycloak*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• *VPC:* prod\n"
                    "• *Signal:* probe could not determine service availability\n"
                    "• *Reason:* timeout\n"
                    "• *Env:* prod"
                ),
            },
        )

    if kind == "service_up":
        return Event(
            source=Source(module="ecs.probe", transport="api", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.other,
            action=sample_action or "service.up",
            outcome=Outcome.success,
            severity=Severity.informational,
            target=Target(id="prod/api-gateway", type="ecs.service",
                          name="api-gateway"),
            extra={
                "vpc": "prod", "name": "api-gateway", "tier": "http",
                "target_id": "prod/api-gateway",
                "prev_status": "down", "status": "up",
                "latency_ms": 210,
                "down_seconds": 720,
                "tags": {"env": "prod", "tier": "http"},
                "message": (
                    "*api-gateway recovered*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• *VPC:* prod\n"
                    "• *Was down for:* 12 min\n"
                    "• *Latency now:* 210 ms\n"
                    "• *Env:* prod"
                ),
            },
        )

    if kind == "probe_agent_stale":
        return Event(
            source=Source(module="ecs.probe", transport="poll", account="095899260107",
                          vendor="aws", region="us-west-1"),
            category=Category.other,
            action=sample_action or "probe.agent.stale",
            outcome=Outcome.failure,
            severity=Severity.critical,
            target=Target(id="prod", type="probe.agent", name="probe-prod"),
            extra={
                "vpc": "prod",
                "last_report": "2026-07-17T14:18:00+00:00",
                "age_seconds": 780,
                "message": (
                    "*Probe agent went silent in `prod`*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• *VPC:* prod\n"
                    "• *Silent for:* 13 min\n"
                    "• *Last report:* 2026-07-17 14:18 UTC\n"
                    "• *Impact:* HTTP/TCP monitoring for this VPC is offline"
                ),
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


@router.post("/notifications/channels/save", dependencies=[Depends(require_role("admin"))])
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


@router.post("/notifications/channels/{channel_id}/toggle", dependencies=[Depends(require_role("admin"))])
def notif_channel_toggle_json(
    channel_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    storage.set_notification_channel_enabled(channel_id, enabled)
    notify_router.get_notifier().reload_channels()
    return {"id": channel_id, "enabled": enabled}


@router.post("/notifications/channels/{channel_id}/test", dependencies=[Depends(require_role("admin"))])
def notif_channel_test_json(channel_id: str) -> dict[str, Any]:
    row = storage.get_notification_channel(channel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return notify_router.get_notifier().send_test(row["name"])


@router.delete("/notifications/channels/{channel_id}", dependencies=[Depends(require_role("admin"))])
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


@router.post("/notifications/rules/save", dependencies=[Depends(require_role("admin"))])
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
    tpl_raw = payload.get("message_template")
    message_template = str(tpl_raw).strip() if isinstance(tpl_raw, str) else None
    storage.upsert_notification_rule(
        rule_id=rid,
        name=name,
        enabled=bool(payload.get("enabled", True)),
        match=match,
        channels=[str(c) for c in channels],
        throttle_seconds=int(payload.get("throttle_seconds", 0)),
        priority=int(payload.get("priority", 100)),
        message_template=message_template or None,
    )
    notify_router.get_notifier().reload_rules()
    return {"id": rid, "saved": True}


@router.post("/notifications/rules/{rule_id}/toggle", dependencies=[Depends(require_role("admin"))])
def notif_rule_toggle_json(
    rule_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    storage.set_notification_rule_enabled(rule_id, enabled)
    notify_router.get_notifier().reload_rules()
    return {"id": rule_id, "enabled": enabled}


@router.post("/notifications/rules/{rule_id}/silence", dependencies=[Depends(require_role("admin"))])
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


@router.delete("/notifications/rules/{rule_id}", dependencies=[Depends(require_role("admin"))])
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


# ---- Routes view (rules grouped by module) ------------------------------

@router.get("/notifications/routes")
def notif_routes_view() -> dict[str, Any]:
    """Configured routes for the /notifications table, plus the module
    catalog and channel list the wizard needs. Only rules with a channel
    are returned as routes — empty modules are not surfaced as rows."""
    from .notify import routes_view
    channels = [
        {"id": str(c["id"]), "name": c["name"], "type": c["type"],
         "enabled": c["enabled"]}
        for c in storage.list_notification_channels()
    ]
    view = routes_view.list_routes()
    return {**view, "channels": channels}


@router.post("/notifications/routes/save", dependencies=[Depends(require_role("admin"))])
def notif_route_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create-or-update a simple route from the wizard. Payload:
      { id?, module, severities:[..], channel, enabled?, message_template? }
    For custom rules with arbitrary conditions, use /notifications/rules/save
    (this endpoint only handles the module+severity shape).
    """
    from .notify import routes_view
    module = str(payload.get("module") or "").strip()
    channel = str(payload.get("channel") or "").strip()
    severities = payload.get("severities") or []
    if not isinstance(severities, list):
        raise HTTPException(status_code=400, detail="severities must be a list")
    enabled = bool(payload.get("enabled", True))
    rule_id = payload.get("id") or None
    tpl_raw = payload.get("message_template")
    message_template = str(tpl_raw).strip() if isinstance(tpl_raw, str) else None
    try:
        rid = routes_view.upsert_simple_route(
            rule_id=rule_id, module=module,
            severities=[str(s) for s in severities],
            channel=channel, enabled=enabled,
            message_template=message_template or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from .notify import router as notify_router_module
    try:
        notify_router_module.get_notifier().reload_rules()
    except Exception:
        pass
    return {"id": rid, "saved": True}


@router.post("/notifications/routes/{rule_id}/toggle", dependencies=[Depends(require_role("admin"))])
def notif_route_toggle(
    rule_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    storage.set_notification_rule_enabled(rule_id, enabled)
    from .notify import router as notify_router_module
    try:
        notify_router_module.get_notifier().reload_rules()
    except Exception:
        pass
    return {"id": rule_id, "enabled": enabled}


@router.post("/notifications/routes/{rule_id}/silence", dependencies=[Depends(require_role("admin"))])
def notif_route_silence(
    rule_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    hours = int(payload.get("hours", 0))
    if hours <= 0:
        storage.set_notification_rule_silence(rule_id, None)
        until = None
    else:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        storage.set_notification_rule_silence(rule_id, until)
    from .notify import router as notify_router_module
    try:
        notify_router_module.get_notifier().reload_rules()
    except Exception:
        pass
    return {"id": rule_id, "silence_until": until.isoformat() if until else None}


@router.delete("/notifications/routes/{rule_id}", dependencies=[Depends(require_role("admin"))])
def notif_route_delete(rule_id: str) -> dict[str, Any]:
    storage.delete_notification_rule(rule_id)
    from .notify import router as notify_router_module
    try:
        notify_router_module.get_notifier().reload_rules()
    except Exception:
        pass
    return {"id": rule_id, "deleted": True}


@router.post("/notifications/cards/{module}/save", dependencies=[Depends(require_role("admin"))])
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


@router.post("/notifications/cards/{module}/silence", dependencies=[Depends(require_role("admin"))])
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


@router.post("/notifications/cards/{module}/test", dependencies=[Depends(require_role("admin"))])
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


@router.post("/notifications/acks", dependencies=[Depends(require_role("admin"))])
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


@router.delete("/notifications/acks/{fingerprint}", dependencies=[Depends(require_role("admin"))])
def notif_ack_delete(fingerprint: str) -> dict[str, Any]:
    storage.remove_notification_ack(fingerprint)
    return {"fingerprint": fingerprint, "cleared": True}


# --- Live ping (drives the navbar live counter) ----------------------------

@router.get("/live/ping")
def live_ping() -> dict[str, Any]:
    """Lightweight poll target for the navbar live indicator. Returns events
    per second over the last 60 seconds. Cheap query — runs every few seconds
    from every open dashboard tab.

    Wrapped in try/except so a transient DB hiccup (pool exhaustion, timeout)
    doesn't turn every open browser tab into a red 500 in the console. We'd
    rather return `{eps: null, error: "..."}` and let the widget go quiet
    than pollute the UI network log every 30 s.
    """
    import logging
    now = datetime.now(timezone.utc)
    try:
        count = storage.event_count_since(now - timedelta(seconds=60))
    except Exception as exc:
        logging.getLogger(__name__).exception("live/ping event_count failed")
        return {
            "ts": now.isoformat(),
            "events_last_60s": None,
            "eps": None,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
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


# ---- RDS Shape B: proxy sources + user allowlist -------------------------

@router.get("/rds/proxy-sources")
def rds_proxy_sources(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    """Every real client IP that has ever touched the RDS Proxy, most-recent
    first. This is the raw feed behind rds.proxy.source.new alerts."""
    rows = storage.list_rds_proxy_sources(limit=limit)
    return {"count": len(rows), "sources": rows}


@router.get("/rds/allowlist")
def rds_allowlist_list() -> dict[str, Any]:
    """The operator-maintained list of expected DB usernames. Any auth
    attempt for a user NOT on this list fires rds.user.unknown."""
    rows = storage.list_rds_user_allowlist()
    return {"count": len(rows), "users": rows}


class _AllowlistAdd(BaseModel):
    username: str
    kind: Literal["human", "service"]
    note: str | None = None


@router.post("/rds/allowlist", dependencies=[Depends(require_role("admin"))])
def rds_allowlist_add(body: _AllowlistAdd) -> dict[str, Any]:
    storage.add_rds_user_allowlist(body.username, body.kind, body.note)
    return {"status": "ok", "username": body.username, "kind": body.kind}


@router.delete("/rds/allowlist/{username}", dependencies=[Depends(require_role("admin"))])
def rds_allowlist_remove(username: str) -> dict[str, Any]:
    storage.remove_rds_user_allowlist(username)
    return {"status": "ok", "username": username}


_SHAPE_B_ACTIONS = (
    "rds.proxy.source.new",
    "rds.session.new_source",
    "rds.user.unknown",
)


@router.get("/rds/shape-b")
def rds_shape_b(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    """Shape-B ('stolen credential / new source') detection feed. Rolls up
    rds.proxy.source.new + rds.session.new_source + rds.user.unknown into
    one endpoint the UI can render as a single unified panel."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    alerts: list[dict[str, Any]] = []
    for action in _SHAPE_B_ACTIONS:
        rows = storage.query_events(
            module="aws.rds", action=action,
            since=since, limit=limit,
        )
        for r in rows:
            extra = r.get("extra") or {}
            actor = r.get("actor") or {}
            target = r.get("target") or {}
            alerts.append({
                "event_id": r.get("event_id"),
                "event_time": r.get("event_time"),
                "action": action,
                "db_instance": extra.get("db_instance") or target.get("id"),
                "user": extra.get("user") or actor.get("principal"),
                "source_ip": extra.get("source_ip") or actor.get("source_ip"),
                "trigger": extra.get("trigger"),
                "message": extra.get("message"),
            })
    alerts.sort(key=lambda a: a.get("event_time") or "", reverse=True)
    return {"count": len(alerts[:limit]), "hours": hours,
            "alerts": alerts[:limit]}


# ---- API Gateway (Phase 1) ------------------------------------------------

@router.get("/api-gw/summary")
def api_gw_summary_endpoint() -> dict[str, Any]:
    """Aggregate counters + last-activity for the /api-gw page header."""
    return storage.api_gw_summary()


@router.get("/api-gw/apis")
def api_gw_apis() -> dict[str, Any]:
    """One row per distinct API name seen in the ingest pipeline —
    powers the 'active APIs' summary at the top of /api-gw."""
    rows = storage.list_api_gw_apis()
    return {"count": len(rows), "apis": rows}


@router.get("/api-gw/sources")
def api_gw_sources(
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Every source IP seen at the API Gateway with per-IP rollups."""
    rows = storage.list_api_sources(limit=limit)
    return {"count": len(rows), "sources": rows}


_API_GW_ALERT_ACTIONS = (
    "api.source.new",
    "api.auth.burst",
    "api.error.burst",
    "api.scanner_ua",
)


@router.get("/api-gw/alerts")
def api_gw_alerts(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    """Recent Shape-A + Shape-B API Gateway alerts — the operator feed."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    alerts: list[dict[str, Any]] = []
    for action in _API_GW_ALERT_ACTIONS:
        rows = storage.query_events(
            module="aws.api_gw", action=action,
            since=since, limit=limit,
        )
        for r in rows:
            extra = r.get("extra") or {}
            actor = r.get("actor") or {}
            target = r.get("target") or {}
            alerts.append({
                "event_id": r.get("event_id"),
                "event_time": r.get("event_time"),
                "action": action,
                "api_name": extra.get("api_name") or target.get("id"),
                "source_ip": extra.get("source_ip") or actor.get("source_ip"),
                "user_agent": extra.get("user_agent"),
                "scanner_signature": extra.get("scanner_signature"),
                "failure_count": extra.get("failure_count"),
                "error_count": extra.get("error_count"),
                "message": extra.get("message"),
            })
    alerts.sort(key=lambda a: a.get("event_time") or "", reverse=True)
    return {"count": len(alerts[:limit]), "hours": hours,
            "alerts": alerts[:limit]}


@router.get("/api-gw/failures")
def api_gw_failures(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    """Raw auth failures + 5xx errors from the API Gateway, most-recent
    first. Used by the /api-gw failures panel."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    for action in ("api.auth.failure", "api.error"):
        rows = storage.query_events(
            module="aws.api_gw", action=action,
            since=since, limit=limit,
        )
        for r in rows:
            extra = r.get("extra") or {}
            actor = r.get("actor") or {}
            target = r.get("target") or {}
            out.append({
                "event_id": r.get("event_id"),
                "event_time": r.get("event_time"),
                "action": action,
                "api_name": extra.get("api_name") or target.get("id"),
                "source_ip": extra.get("source_ip") or actor.get("source_ip"),
                "method": extra.get("method"),
                "status": extra.get("status"),
                "user_agent": extra.get("user_agent"),
                "reason": extra.get("reason"),
                "response_latency_ms": extra.get("response_latency_ms"),
            })
    out.sort(key=lambda x: x.get("event_time") or "", reverse=True)
    return {"count": len(out[:limit]), "hours": hours, "failures": out[:limit]}




@router.get("/intel/status")
def intel_status() -> dict[str, Any]:
    return {"feeds": intel_db.feed_meta()}


@router.get("/intel/lookup")
def intel_lookup(ip: str) -> dict[str, Any]:
    """Read local feed and optional GeoIP context for a single IP."""
    candidate = ip.strip()
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ip must be a valid IPv4 or IPv6 address") from exc
    return {"ip": str(parsed), "intel": intel_enrich.lookup_ip(str(parsed))}


# ---------- Storage overview (S3 / EBS / RDS / EFS / Backup / Secrets) -------

# Action-prefix -> group name. Secrets Manager lives under `iam` category, not
# `storage`, so we can't just filter by category — group by prefix instead.
_STORAGE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("s3",      ("s3.",)),
    ("ebs",     ("storage.snapshot.", "storage.volume.", "compute.ami.")),
    ("rds",     ("rds.",)),
    ("efs",     ("efs.",)),
    ("backup",  ("backup.",)),
    ("secrets", ("secrets.",)),
)


def _classify_storage(action: str) -> str | None:
    for group, prefixes in _STORAGE_GROUPS:
        for p in prefixes:
            if action.startswith(p):
                return group
    return None


def _s3_security_signal(event: dict[str, Any]) -> str | None:
    """Return a label for high-value S3 object activity.

    Normal S3 request volume stays in the canonical Events stream. The
    Storage page only surfaces requests that need investigation.
    """
    action = event.get("action") or ""
    if action == "s3.object.access.anonymous":
        return "Anonymous access"
    if action != "s3.object.access":
        return None
    intel = (event.get("extra") or {}).get("intel") or {}
    if intel.get("is_tor") is True:
        return "Tor exit node"
    if intel.get("feeds"):
        return "Threat-intel match"
    return None


def _s3_security_reason(event: dict[str, Any], signal: str) -> str:
    if signal == "Anonymous access":
        return "S3 access log Requester was '-' (no authenticated AWS requester)."
    if signal == "Tor exit node":
        return "The source IP was identified as a Tor exit node."
    if signal == "Threat-intel match":
        return "The source IP matched one or more configured threat-intelligence feeds."
    return "S3 access matched a security signal."


@router.get("/storage/summary")
def storage_summary(hours: int = Query(default=24, ge=1, le=168)) -> dict[str, Any]:
    """Unified counts across all storage domains + a small recent-critical list.
    Used by the /ui/storage page. Cheap: two queries."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Bucket inventory (existing).
    buckets = storage.list_bucket_status()
    public_count = sum(1 for b in buckets if b.get("public"))

    # Storage-relevant events in the window. Over-fetch and filter in Python
    # (query_events doesn't support prefix match). 5000 covers ~ any real load
    # for the 24h default; escalate limit if hours is large.
    events = storage.query_events(since=since, limit=5000)

    per_group = {g: {"total": 0, "critical": 0, "high": 0} for g, _ in _STORAGE_GROUPS}
    recent_critical: list[dict[str, Any]] = []
    s3_security_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for ev in events:
        action = ev.get("action") or ""
        group = _classify_storage(action)
        if group is None:
            continue
        per_group[group]["total"] += 1
        sev = (ev.get("severity") or "").lower()
        if sev in ("critical", "high"):
            per_group[group][sev] += 1
            if group == "s3":
                signal = _s3_security_signal(ev)
                if signal:
                    extra = ev.get("extra") or {}
                    target = ev.get("target") or {}
                    actor = ev.get("actor") or {}
                    target_id = str(target.get("id") or "unknown target")
                    key = (signal, target_id)
                    bucket = s3_security_groups.setdefault(key, {
                        "event_id": ev.get("event_id"),
                        "event_time": ev.get("event_time"),
                        "action": action,
                        "signal": signal,
                        "group": group,
                        "severity": sev,
                        "message": extra.get("message"),
                        "reason": _s3_security_reason(ev, signal),
                        "target_id": target_id,
                        "principal": actor.get("principal"),
                        "source_ips": [],
                        "count": 0,
                    })
                    bucket["count"] += 1
                    source_ip = actor.get("source_ip")
                    if source_ip and source_ip not in bucket["source_ips"]:
                        bucket["source_ips"].append(source_ip)
            if sev == "critical" and len(recent_critical) < 20:
                extra = ev.get("extra") or {}
                target = ev.get("target") or {}
                actor = ev.get("actor") or {}
                recent_critical.append({
                    "event_id": ev.get("event_id"),
                    "event_time": ev.get("event_time"),
                    "action": action,
                    "group": group,
                    "severity": sev,
                    "message": extra.get("message"),
                    "target_id": target.get("id"),
                    "principal": actor.get("principal"),
                    "source_ip": actor.get("source_ip"),
                })

    return {
        "hours": hours,
        "buckets": {
            "total": len(buckets),
            "public": public_count,
        },
        "groups": per_group,
        "recent_s3_security": sorted(
            s3_security_groups.values(),
            key=lambda item: item.get("event_time") or "",
            reverse=True,
        )[:50],
        "recent_critical": recent_critical,
    }


# ---------- UEBA (baselines + first-seen anomalies) --------------------------

@router.get("/ueba/baselines")
def ueba_baselines(
    principal_type: str | None = None,
    principal_id: str | None = None,
    dimension: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    from .ueba import db as ueba_db
    rows = ueba_db.query_baselines(
        principal_type=principal_type,
        principal_id=principal_id,
        dimension=dimension,
        limit=limit,
    )
    return {"count": len(rows), "baselines": rows}


@router.get("/ueba/anomalies")
def ueba_anomalies(
    limit: int = Query(default=200, ge=1, le=1000),
    principal: str | None = None,
) -> dict[str, Any]:
    # first-seen anomaly events live in the main events table with an action
    # that contains ".anomaly.first_seen_". query_events has no LIKE filter,
    # so over-fetch then filter in Python.
    rows = storage.query_events(
        actor_principal=principal,
        limit=max(limit * 4, 200),
    )
    out = [r for r in rows if ".anomaly.first_seen_" in (r.get("action") or "")]
    return {"count": len(out[:limit]), "anomalies": out[:limit]}
