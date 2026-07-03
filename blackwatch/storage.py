"""Persistence + query for normalized events. The only module allowed to
touch SQL. Everything else speaks in Event objects / plain dicts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from .db import get_pool
from .event import Event

_INSERT = """
INSERT INTO events (
    event_id, schema_version, event_time, ingested_at, dedup_fingerprint,
    module, vendor, account, region, transport,
    category, action, outcome,
    actor_principal, actor_type, actor_is_root, actor_source_ip,
    target_id, target_type,
    severity, tags, envelope, raw
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s
)
ON CONFLICT (event_id) DO NOTHING
RETURNING event_id
"""


def insert_event(ev: Event) -> bool:
    """Insert one event. Returns True if a new row was written, False if the
    event_id already existed (silent dedup at the DB layer).

    The caller uses the bool to decide whether to dispatch notifications.
    Without this, re-shipped lines (heartbeat overlap with the realtime
    follower) would silently no-op at the DB but still trigger N copies of
    the same Slack/email/PagerDuty notification.
    """
    envelope = ev.model_dump(mode="json")
    params = (
        ev.event_id,
        ev.schema_version,
        ev.event_time,
        ev.ingested_at,
        ev.dedup_fingerprint,
        ev.source.module,
        ev.source.vendor,
        ev.source.account,
        ev.source.region,
        ev.source.transport.value,
        ev.category.value,
        ev.action,
        ev.outcome.value,
        ev.actor.principal,
        ev.actor.type.value if ev.actor.type else None,
        ev.actor.is_root,
        ev.actor.source_ip,
        ev.target.id,
        ev.target.type,
        ev.severity.value if ev.severity else None,
        ev.tags,
        Jsonb(envelope),
        Jsonb(ev.raw),
    )
    with get_pool().connection() as conn:
        cur = conn.execute(_INSERT, params)
        # RETURNING gives one row on insert, zero on conflict.
        return cur.fetchone() is not None


def query_events(
    *,
    module: str | None = None,
    category: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    severity: str | None = None,
    severities: list[str] | None = None,
    actor_principal: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    def add(clause: str, value: Any) -> None:
        clauses.append(clause)
        params.append(value)

    if module:
        add("module = %s", module)
    if category:
        add("category = %s", category)
    if action:
        add("action = %s", action)
    if outcome:
        add("outcome = %s", outcome)
    if severity:
        add("severity = %s", severity)
    if severities:
        add("severity = ANY(%s)", list(severities))
    if actor_principal:
        add("actor_principal = %s", actor_principal)
    if target_id:
        add("target_id = %s", target_id)
    if since:
        add("event_time >= %s", since)
    if until:
        add("event_time <= %s", until)
    if q:
        # Phase 0 free-text: substring match over the serialized envelope.
        add("envelope::text ILIKE %s", f"%{q}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT envelope FROM events {where} ORDER BY event_time DESC LIMIT %s"
    params.append(min(max(limit, 1), 1000))

    with get_pool().connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row[0] for row in rows]


def get_event(event_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT envelope FROM events WHERE event_id = %s", (event_id,)
        ).fetchone()
    return row[0] if row else None


def severity_counts() -> dict[str, int]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT COALESCE(severity, 'unscored') AS sev, count(*) FROM events GROUP BY sev"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


# --- VPN live-state read-model -------------------------------------------------

def get_vpn_status(server: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT server, updated_at, active, clients, certs "
            "FROM vpn_status WHERE server = %s",
            (server,),
        ).fetchone()
    if row is None:
        return None
    return {
        "server": row[0], "updated_at": row[1], "active": row[2],
        "clients": row[3], "certs": row[4],
    }


def list_vpn_status() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT server, updated_at, active, clients, certs "
            "FROM vpn_status ORDER BY server"
        ).fetchall()
    return [
        {
            "server": r[0], "updated_at": r[1], "active": r[2],
            "clients": r[3], "certs": r[4],
        }
        for r in rows
    ]


def delete_vpn_status(server: str) -> None:
    """Remove a VPN server row entirely — used by the UI to clear stale
    entries from a renamed/decommissioned agent."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM vpn_status WHERE server = %s", (server,))


def upsert_vpn_certs(
    server: str, certs: list[dict[str, Any]], updated_at: datetime
) -> None:
    """Replace the cert inventory for a server. Called by the projection on
    every vpn.cert.snapshot event from the agent's heartbeat."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO vpn_status (server, updated_at, active, clients, certs)
            VALUES (%s, %s, NULL, NULL, %s)
            ON CONFLICT (server) DO UPDATE
              SET certs = EXCLUDED.certs, updated_at = EXCLUDED.updated_at
            """,
            (server, updated_at, Jsonb(certs)),
        )


def upsert_vpn_health(server: str, active: bool, updated_at: datetime) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO vpn_status (server, updated_at, active, clients)
            VALUES (%s, %s, %s, NULL)
            ON CONFLICT (server) DO UPDATE
              SET active = EXCLUDED.active, updated_at = EXCLUDED.updated_at
            """,
            (server, updated_at, active),
        )


def upsert_vpn_clients(
    server: str, clients: list[dict[str, Any]], updated_at: datetime
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO vpn_status (server, updated_at, active, clients)
            VALUES (%s, %s, NULL, %s)
            ON CONFLICT (server) DO UPDATE
              SET clients = EXCLUDED.clients, updated_at = EXCLUDED.updated_at
            """,
            (server, updated_at, Jsonb(clients)),
        )


# --- Connectors ----------------------------------------------------------------

_CONNECTOR_COLS = (
    "id, name, type, enabled, verified, config, last_run_at, last_status, last_error"
)


def _connector_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "type": row[2],
        "enabled": row[3],
        "verified": row[4],
        "config": row[5],
        "last_run_at": row[6],
        "last_status": row[7],
        "last_error": row[8],
    }


def list_connectors() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {_CONNECTOR_COLS} FROM connectors ORDER BY name"
        ).fetchall()
    return [_connector_row(r) for r in rows]


def get_connector(connector_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_CONNECTOR_COLS} FROM connectors WHERE id = %s", (connector_id,)
        ).fetchone()
    return _connector_row(row) if row else None


def upsert_connector(
    connector_id: str, name: str, ctype: str, config: dict[str, Any]
) -> None:
    """Create or update a connector's editable fields. Editing config resets
    `verified` (host/key may have changed) so it must be re-tested."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO connectors (id, name, type, config)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name,
                  config = EXCLUDED.config,
                  verified = false,
                  updated_at = now()
            """,
            (connector_id, name, ctype, Jsonb(config)),
        )


def set_connector_enabled(connector_id: str, enabled: bool) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE connectors SET enabled = %s, updated_at = now() WHERE id = %s",
            (enabled, connector_id),
        )


def set_connector_status(
    connector_id: str,
    *,
    last_status: str,
    last_error: str | None,
    last_run_at: datetime,
    verified: bool | None = None,
) -> None:
    with get_pool().connection() as conn:
        if verified is None:
            conn.execute(
                "UPDATE connectors SET last_status=%s, last_error=%s, last_run_at=%s WHERE id=%s",
                (last_status, last_error, last_run_at, connector_id),
            )
        else:
            conn.execute(
                "UPDATE connectors SET last_status=%s, last_error=%s, last_run_at=%s, verified=%s WHERE id=%s",
                (last_status, last_error, last_run_at, verified, connector_id),
            )


def delete_connector(connector_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM connectors WHERE id = %s", (connector_id,))


# --- Dashboard controls: rule overrides, muted actions, volume -----------------

def get_rule_overrides() -> dict[str, bool]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT rule_id, enabled FROM rule_overrides").fetchall()
    return {r[0]: r[1] for r in rows}


def set_rule_override(rule_id: str, enabled: bool) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO rule_overrides (rule_id, enabled) VALUES (%s, %s)
            ON CONFLICT (rule_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
            (rule_id, enabled),
        )


def list_muted_actions() -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT action FROM muted_actions ORDER BY action").fetchall()
    return [r[0] for r in rows]


def add_muted_action(action: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO muted_actions (action) VALUES (%s) ON CONFLICT DO NOTHING", (action,)
        )


def remove_muted_action(action: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM muted_actions WHERE action = %s", (action,))


def action_counts(since: datetime, limit: int = 15) -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT action, count(*) FROM events
            WHERE event_time >= %s
            GROUP BY action ORDER BY count(*) DESC LIMIT %s
            """,
            (since, limit),
        ).fetchall()
    return [{"action": r[0], "count": r[1]} for r in rows]


def event_count_since(since: datetime) -> int:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT count(*) FROM events WHERE event_time >= %s", (since,)
        ).fetchone()
    return row[0] if row else 0


# --- EC2 host read-model -------------------------------------------------------

_HOST_COLS = "instance_id, hostname, account, region, updated_at, active, extra, snapshots"


def _host_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "instance_id": row[0],
        "hostname": row[1],
        "account": row[2],
        "region": row[3],
        "updated_at": row[4],
        "active": row[5],
        "extra": row[6],
        "snapshots": row[7] if len(row) > 7 else None,
    }


def list_host_status() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {_HOST_COLS} FROM host_status ORDER BY hostname, instance_id"
        ).fetchall()
    return [_host_row(r) for r in rows]


def get_host_status(instance_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_HOST_COLS} FROM host_status WHERE instance_id = %s", (instance_id,)
        ).fetchone()
    return _host_row(row) if row else None


def get_host_snapshots(instance_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT snapshots FROM host_status WHERE instance_id = %s", (instance_id,)
        ).fetchone()
    return row[0] if row else None


def set_host_snapshots(
    instance_id: str, snapshots: dict[str, Any], updated_at: datetime
) -> None:
    """Upsert just the snapshots column (heartbeat normally created the row;
    if not, create a minimal one)."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO host_status (instance_id, updated_at, snapshots) VALUES (%s, %s, %s)
            ON CONFLICT (instance_id) DO UPDATE
              SET snapshots = EXCLUDED.snapshots, updated_at = EXCLUDED.updated_at
            """,
            (instance_id, updated_at, Jsonb(snapshots)),
        )


def upsert_host_status(
    instance_id: str,
    *,
    hostname: str | None,
    account: str | None,
    region: str | None,
    updated_at: datetime,
    active: bool,
    extra: dict[str, Any] | None,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO host_status (instance_id, hostname, account, region, updated_at, active, extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instance_id) DO UPDATE
              SET hostname = EXCLUDED.hostname,
                  account = EXCLUDED.account,
                  region = EXCLUDED.region,
                  updated_at = EXCLUDED.updated_at,
                  active = EXCLUDED.active,
                  extra = EXCLUDED.extra
            """,
            (instance_id, hostname, account, region, updated_at, active, Jsonb(extra or {})),
        )


def set_host_active(instance_id: str, active: bool) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE host_status SET active = %s WHERE instance_id = %s", (active, instance_id)
        )


# --- Notification rules --------------------------------------------------------

_NRULE_COLS = "id, name, enabled, match, channels, throttle_seconds, silence_until, priority"


def _nrule_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0], "name": row[1], "enabled": row[2], "match": row[3],
        "channels": list(row[4] or []), "throttle_seconds": row[5],
        "silence_until": row[6], "priority": row[7],
    }


def list_notification_rules() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {_NRULE_COLS} FROM notification_rules ORDER BY priority, name"
        ).fetchall()
    return [_nrule_row(r) for r in rows]


def get_notification_rule(rule_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_NRULE_COLS} FROM notification_rules WHERE id = %s", (rule_id,)
        ).fetchone()
    return _nrule_row(row) if row else None


def upsert_notification_rule(
    rule_id: str,
    name: str,
    enabled: bool,
    match: dict[str, Any],
    channels: list[str],
    throttle_seconds: int = 0,
    priority: int = 100,
) -> None:
    """Create or update editable fields. Does NOT touch silence_until — that is
    managed by set_notification_rule_silence so the Save flow can't accidentally
    un-silence a rule mid-maintenance-window."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_rules (id, name, enabled, match, channels, throttle_seconds, priority)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name, enabled = EXCLUDED.enabled,
                  match = EXCLUDED.match, channels = EXCLUDED.channels,
                  throttle_seconds = EXCLUDED.throttle_seconds,
                  priority = EXCLUDED.priority,
                  updated_at = now()
            """,
            (rule_id, name, enabled, Jsonb(match), list(channels), throttle_seconds, priority),
        )


def set_notification_rule_enabled(rule_id: str, enabled: bool) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE notification_rules SET enabled = %s, updated_at = now() WHERE id = %s",
            (enabled, rule_id),
        )


def set_notification_rule_silence(rule_id: str, silence_until: datetime | None) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE notification_rules SET silence_until = %s, updated_at = now() WHERE id = %s",
            (silence_until, rule_id),
        )


def delete_notification_rule(rule_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM notification_rules WHERE id = %s", (rule_id,))


# --- Notification channels (Phase 2) ------------------------------------------

_NCHAN_COLS = (
    "id, name, type, enabled, config, message_template, retries, retry_backoff_seconds, "
    "rate_limit_per_min, dedup_window_seconds, digest_window_seconds, "
    "last_status, last_error, last_sent_at"
)


def _nchan_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0], "name": row[1], "type": row[2], "enabled": row[3],
        "config": row[4] or {}, "message_template": row[5],
        "retries": row[6], "retry_backoff_seconds": row[7],
        "rate_limit_per_min": row[8], "dedup_window_seconds": row[9],
        "digest_window_seconds": row[10],
        "last_status": row[11], "last_error": row[12], "last_sent_at": row[13],
    }


def list_notification_channels() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {_NCHAN_COLS} FROM notification_channels ORDER BY name"
        ).fetchall()
    return [_nchan_row(r) for r in rows]


def get_notification_channel(channel_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_NCHAN_COLS} FROM notification_channels WHERE id = %s", (channel_id,)
        ).fetchone()
    return _nchan_row(row) if row else None


def get_notification_channel_by_name(name: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_NCHAN_COLS} FROM notification_channels WHERE name = %s", (name,)
        ).fetchone()
    return _nchan_row(row) if row else None


def upsert_notification_channel(
    channel_id: str,
    name: str,
    ctype: str,
    enabled: bool,
    config: dict[str, Any],
    message_template: str | None,
    retries: int,
    retry_backoff_seconds: int,
    rate_limit_per_min: int,
    dedup_window_seconds: int,
    digest_window_seconds: int,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_channels (
                id, name, type, enabled, config, message_template,
                retries, retry_backoff_seconds, rate_limit_per_min,
                dedup_window_seconds, digest_window_seconds
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name, type = EXCLUDED.type, enabled = EXCLUDED.enabled,
                  config = EXCLUDED.config, message_template = EXCLUDED.message_template,
                  retries = EXCLUDED.retries, retry_backoff_seconds = EXCLUDED.retry_backoff_seconds,
                  rate_limit_per_min = EXCLUDED.rate_limit_per_min,
                  dedup_window_seconds = EXCLUDED.dedup_window_seconds,
                  digest_window_seconds = EXCLUDED.digest_window_seconds,
                  updated_at = now()
            """,
            (channel_id, name, ctype, enabled, Jsonb(config), message_template,
             retries, retry_backoff_seconds, rate_limit_per_min,
             dedup_window_seconds, digest_window_seconds),
        )


def set_notification_channel_enabled(channel_id: str, enabled: bool) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE notification_channels SET enabled=%s, updated_at=now() WHERE id=%s",
            (enabled, channel_id),
        )


def set_notification_channel_status(
    channel_id: str, status: str, error: str | None, sent_at: datetime | None
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE notification_channels "
            "SET last_status=%s, last_error=%s, last_sent_at=COALESCE(%s, last_sent_at) "
            "WHERE id=%s",
            (status, error, sent_at, channel_id),
        )


def delete_notification_channel(channel_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM notification_channels WHERE id=%s", (channel_id,))


# --- Notification log (Phase 2) -----------------------------------------------

def insert_notification_log(entry: dict[str, Any]) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_log (
                rule_id, rule_name, channel_id, channel_name,
                event_id, event_action, event_severity,
                status, retries_used, body_preview, error_message
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry.get("rule_id"), entry.get("rule_name"),
                entry.get("channel_id"), entry.get("channel_name"),
                entry.get("event_id"), entry.get("event_action"), entry.get("event_severity"),
                entry["status"], entry.get("retries_used", 0),
                (entry.get("body_preview") or "")[:2000],
                (entry.get("error_message") or None),
            ),
        )


def list_notification_log(
    *, status: str | None = None, channel_name: str | None = None,
    rule_name: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if status:        clauses.append("status = %s");        params.append(status)
    if channel_name:  clauses.append("channel_name = %s");  params.append(channel_name)
    if rule_name:     clauses.append("rule_name = %s");     params.append(rule_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(min(max(limit, 1), 1000))
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, ts, rule_name, channel_name, event_id, event_action,
                   event_severity, status, retries_used, body_preview, error_message
            FROM notification_log {where} ORDER BY ts DESC LIMIT %s
            """,
            params,
        ).fetchall()
    return [
        {
            "id": r[0], "ts": r[1], "rule_name": r[2], "channel_name": r[3],
            "event_id": r[4], "event_action": r[5], "event_severity": r[6],
            "status": r[7], "retries_used": r[8], "body_preview": r[9], "error_message": r[10],
        }
        for r in rows
    ]


# --- Acks ---------------------------------------------------------------------

def list_notification_acks() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT fingerprint, ack_until, reason, created_at "
            "FROM notification_acks WHERE ack_until > now() ORDER BY ack_until"
        ).fetchall()
    return [
        {"fingerprint": r[0], "ack_until": r[1], "reason": r[2], "created_at": r[3]}
        for r in rows
    ]


def is_fingerprint_acked(fingerprint: str) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM notification_acks WHERE fingerprint=%s AND ack_until > now()",
            (fingerprint,),
        ).fetchone()
    return row is not None


def add_notification_ack(
    fingerprint: str, ack_until: datetime, reason: str | None = None
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_acks (fingerprint, ack_until, reason)
            VALUES (%s, %s, %s)
            ON CONFLICT (fingerprint) DO UPDATE
              SET ack_until = EXCLUDED.ack_until, reason = EXCLUDED.reason
            """,
            (fingerprint, ack_until, reason),
        )


def remove_notification_ack(fingerprint: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM notification_acks WHERE fingerprint=%s", (fingerprint,))


# --- ECS service probe read-model --------------------------------------------

_TARGET_COLS = "id, name, vpc, tier, config, severity_when_down, tags, enabled, created_at"


def _target_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]), "name": row[1], "vpc": row[2], "tier": row[3],
        "config": row[4] or {}, "severity_when_down": row[5],
        "tags": row[6] or {}, "enabled": row[7], "created_at": row[8],
    }


def list_probe_targets(vpc: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = f"SELECT {_TARGET_COLS} FROM probe_targets"
    where, args = [], []
    if vpc is not None:
        where.append("vpc = %s"); args.append(vpc)
    if enabled_only:
        where.append("enabled = TRUE")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY vpc, name"
    with get_pool().connection() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [_target_row(r) for r in rows]


def get_probe_target(target_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_TARGET_COLS} FROM probe_targets WHERE id = %s", (target_id,)
        ).fetchone()
    return _target_row(row) if row else None


def upsert_probe_target(
    target_id: str, *, name: str, vpc: str, tier: str,
    config: dict[str, Any], severity_when_down: str,
    tags: dict[str, Any] | None, enabled: bool,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO probe_targets (id, name, vpc, tier, config, severity_when_down, tags, enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name, vpc = EXCLUDED.vpc, tier = EXCLUDED.tier,
                  config = EXCLUDED.config,
                  severity_when_down = EXCLUDED.severity_when_down,
                  tags = EXCLUDED.tags, enabled = EXCLUDED.enabled
            """,
            (target_id, name, vpc, tier, Jsonb(config),
             severity_when_down, Jsonb(tags or {}), enabled),
        )


def delete_probe_target(target_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM probe_targets WHERE id = %s", (target_id,))


_SS_COLS = ("target_id, vpc, name, tier, status, last_seen, latency_ms, "
            "consecutive_fails, consecutive_success, down_since, extra")


def _ss_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "target_id": str(row[0]), "vpc": row[1], "name": row[2], "tier": row[3],
        "status": row[4], "last_seen": row[5], "latency_ms": row[6],
        "consecutive_fails": row[7], "consecutive_success": row[8],
        "down_since": row[9],
        "extra": row[10] or {},
    }


def list_service_status(vpc: str | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT {_SS_COLS} FROM service_status"
    args: tuple[Any, ...] = ()
    if vpc is not None:
        sql += " WHERE vpc = %s"; args = (vpc,)
    sql += " ORDER BY vpc, name"
    with get_pool().connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_ss_row(r) for r in rows]


def get_service_status(target_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_SS_COLS} FROM service_status WHERE target_id = %s", (target_id,)
        ).fetchone()
    return _ss_row(row) if row else None


def upsert_service_status(
    target_id: str, *, vpc: str, name: str, tier: str,
    status: str, last_seen: datetime, latency_ms: int | None,
    consecutive_fails: int, consecutive_success: int,
    down_since: datetime | None,
    extra: dict[str, Any] | None,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO service_status
              (target_id, vpc, name, tier, status, last_seen, latency_ms,
               consecutive_fails, consecutive_success, down_since, extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (target_id) DO UPDATE
              SET vpc=EXCLUDED.vpc, name=EXCLUDED.name, tier=EXCLUDED.tier,
                  status=EXCLUDED.status, last_seen=EXCLUDED.last_seen,
                  latency_ms=EXCLUDED.latency_ms,
                  consecutive_fails=EXCLUDED.consecutive_fails,
                  consecutive_success=EXCLUDED.consecutive_success,
                  down_since=EXCLUDED.down_since,
                  extra=EXCLUDED.extra
            """,
            (target_id, vpc, name, tier, status, last_seen, latency_ms,
             consecutive_fails, consecutive_success, down_since, Jsonb(extra or {})),
        )


def list_probe_agents() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT vpc, last_report, agent_version, active FROM probe_agent_status ORDER BY vpc"
        ).fetchall()
    return [{"vpc": r[0], "last_report": r[1], "agent_version": r[2], "active": r[3]} for r in rows]


def get_probe_agent(vpc: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT vpc, last_report, agent_version, active FROM probe_agent_status WHERE vpc=%s",
            (vpc,),
        ).fetchone()
    if not row:
        return None
    return {"vpc": row[0], "last_report": row[1], "agent_version": row[2], "active": row[3]}


def upsert_probe_agent(vpc: str, *, last_report: datetime, agent_version: str | None, active: bool) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO probe_agent_status (vpc, last_report, agent_version, active)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (vpc) DO UPDATE
              SET last_report = EXCLUDED.last_report,
                  agent_version = EXCLUDED.agent_version,
                  active = EXCLUDED.active
            """,
            (vpc, last_report, agent_version, active),
        )


# --- S3 bucket inventory read-model ------------------------------------------

_BUCKET_COLS = ("bucket_name, region, account, created_date, first_seen, last_scan, "
                "public, public_reasons, encryption, versioning, mfa_delete, "
                "block_public_access, logging_target, policy, tags, extra")


def _bucket_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "bucket_name": row[0], "region": row[1], "account": row[2],
        "created_date": row[3], "first_seen": row[4], "last_scan": row[5],
        "public": row[6], "public_reasons": row[7] or [],
        "encryption": row[8], "versioning": row[9], "mfa_delete": row[10],
        "block_public_access": row[11] or {},
        "logging_target": row[12], "policy": row[13],
        "tags": row[14] or {}, "extra": row[15] or {},
    }


def list_bucket_status(
    public_only: bool = False, unencrypted_only: bool = False,
) -> list[dict[str, Any]]:
    sql = f"SELECT {_BUCKET_COLS} FROM bucket_status"
    where = []
    if public_only:
        where.append("public = TRUE")
    if unencrypted_only:
        where.append("encryption = 'none'")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY public DESC NULLS LAST, account, region, bucket_name"
    with get_pool().connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [_bucket_row(r) for r in rows]


def get_bucket_status(bucket_name: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_BUCKET_COLS} FROM bucket_status WHERE bucket_name = %s",
            (bucket_name,),
        ).fetchone()
    return _bucket_row(row) if row else None


def upsert_bucket_status(
    bucket_name: str, *,
    region: str | None, account: str | None,
    created_date: datetime | None, last_scan: datetime,
    public: bool, public_reasons: list[str],
    encryption: str, versioning: str, mfa_delete: bool,
    block_public_access: dict[str, Any],
    logging_target: str | None, policy: str | None,
    tags: dict[str, Any] | None, extra: dict[str, Any] | None,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO bucket_status
              (bucket_name, region, account, created_date, last_scan,
               public, public_reasons, encryption, versioning, mfa_delete,
               block_public_access, logging_target, policy, tags, extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bucket_name) DO UPDATE
              SET region = EXCLUDED.region, account = EXCLUDED.account,
                  created_date = COALESCE(EXCLUDED.created_date, bucket_status.created_date),
                  last_scan = EXCLUDED.last_scan,
                  public = EXCLUDED.public,
                  public_reasons = EXCLUDED.public_reasons,
                  encryption = EXCLUDED.encryption,
                  versioning = EXCLUDED.versioning,
                  mfa_delete = EXCLUDED.mfa_delete,
                  block_public_access = EXCLUDED.block_public_access,
                  logging_target = EXCLUDED.logging_target,
                  policy = EXCLUDED.policy,
                  tags = EXCLUDED.tags,
                  extra = EXCLUDED.extra
            """,
            (bucket_name, region, account, created_date, last_scan,
             public, Jsonb(public_reasons or []),
             encryption, versioning, mfa_delete,
             Jsonb(block_public_access or {}),
             logging_target, policy,
             Jsonb(tags or {}), Jsonb(extra or {})),
        )


def delete_bucket_status(bucket_name: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM bucket_status WHERE bucket_name = %s", (bucket_name,))


def list_bucket_names() -> set[str]:
    """For drift-scan reconciliation: returns the set of bucket names BW has
    ever seen, so the scan can detect ones that disappeared between runs."""
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT bucket_name FROM bucket_status").fetchall()
    return {r[0] for r in rows}


# --- AWS posture findings read-model -----------------------------------------

_FINDING_COLS = ("finding_id, resource_id, resource_type, finding_type, severity, "
                 "region, account, evidence, first_seen, last_seen, resolved_at")


def _finding_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "finding_id": row[0], "resource_id": row[1], "resource_type": row[2],
        "finding_type": row[3], "severity": row[4], "region": row[5],
        "account": row[6], "evidence": row[7] or {},
        "first_seen": row[8], "last_seen": row[9], "resolved_at": row[10],
    }


def list_posture_findings(
    unresolved_only: bool = True,
    resource_type: str | None = None,
    account: str | None = None,
) -> list[dict[str, Any]]:
    sql = f"SELECT {_FINDING_COLS} FROM posture_findings"
    where: list[str] = []
    args: list[Any] = []
    if unresolved_only:
        where.append("resolved_at IS NULL")
    if resource_type is not None:
        where.append("resource_type = %s"); args.append(resource_type)
    if account is not None:
        where.append("account = %s"); args.append(account)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (" ORDER BY CASE severity "
            "WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 "
            "WHEN 'low' THEN 3 ELSE 4 END, last_seen DESC")
    with get_pool().connection() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [_finding_row(r) for r in rows]


def get_posture_finding(finding_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_FINDING_COLS} FROM posture_findings WHERE finding_id = %s",
            (finding_id,),
        ).fetchone()
    return _finding_row(row) if row else None


def upsert_posture_finding(
    finding_id: str, *,
    resource_id: str, resource_type: str, finding_type: str,
    severity: str, region: str | None, account: str | None,
    evidence: dict[str, Any] | None, last_seen: datetime,
) -> bool:
    """Returns True if this was a NEW finding (insert), False if it was an
    existing one being re-confirmed (update). Caller uses this to know whether
    to fire a finding.new event."""
    with get_pool().connection() as conn:
        result = conn.execute(
            """
            INSERT INTO posture_findings
              (finding_id, resource_id, resource_type, finding_type, severity,
               region, account, evidence, last_seen, resolved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
            ON CONFLICT (finding_id) DO UPDATE
              SET severity = EXCLUDED.severity,
                  region = EXCLUDED.region,
                  account = EXCLUDED.account,
                  evidence = EXCLUDED.evidence,
                  last_seen = EXCLUDED.last_seen,
                  -- If a finding was previously resolved and is now back, treat
                  -- that as a re-open: clear resolved_at and keep first_seen.
                  resolved_at = NULL
              RETURNING (xmax = 0) AS inserted
            """,
            (finding_id, resource_id, resource_type, finding_type, severity,
             region, account, Jsonb(evidence or {}), last_seen),
        ).fetchone()
    return bool(result and result[0])


def mark_posture_finding_resolved(finding_id: str, resolved_at: datetime) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE posture_findings SET resolved_at = %s "
            "WHERE finding_id = %s AND resolved_at IS NULL",
            (resolved_at, finding_id),
        )


# --- Performance alert rules (host metric thresholds) ---------------------

_PERF_COLS = (
    "id, name, enabled, created_at, updated_at, "
    "module, instance_id, tag_key, tag_value, "
    "metric, comparison, threshold, "
    "window_seconds, min_breach_ratio, "
    "severity, channels, throttle_seconds, "
    "samples, last_fired_at, last_value"
)


def _perf_rule_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "name": row[1],
        "enabled": bool(row[2]),
        "created_at": row[3].isoformat() if row[3] else None,
        "updated_at": row[4].isoformat() if row[4] else None,
        "module": row[5],
        "instance_id": row[6],
        "tag_key": row[7],
        "tag_value": row[8],
        "metric": row[9],
        "comparison": row[10],
        "threshold": float(row[11]),
        "window_seconds": int(row[12]),
        "min_breach_ratio": float(row[13]),
        "severity": row[14],
        "channels": row[15] or [],
        "throttle_seconds": int(row[16]),
        "samples": row[17] or [],
        "last_fired_at": row[18],   # keep as datetime for evaluator math
        "last_value": float(row[19]) if row[19] is not None else None,
    }


def list_perf_alert_rules() -> list[dict[str, Any]]:
    """Every rule (enabled + disabled), for the management UI."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {_PERF_COLS} FROM perf_alert_rules ORDER BY created_at DESC"
        ).fetchall()
    return [_perf_rule_row(r) for r in rows]


def get_perf_alert_rule(rule_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            f"SELECT {_PERF_COLS} FROM perf_alert_rules WHERE id = %s",
            (rule_id,),
        ).fetchone()
    return _perf_rule_row(row) if row else None


def list_enabled_perf_rules_for_module(module: str) -> list[dict[str, Any]]:
    """Used by the evaluator on each heartbeat — small, cached-ish."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {_PERF_COLS} FROM perf_alert_rules "
            "WHERE enabled = TRUE AND module = %s",
            (module,),
        ).fetchall()
    return [_perf_rule_row(r) for r in rows]


def upsert_perf_alert_rule(
    rule_id: str,
    *,
    name: str,
    enabled: bool,
    module: str,
    instance_id: str | None,
    tag_key: str | None,
    tag_value: str | None,
    metric: str,
    comparison: str,
    threshold: float,
    window_seconds: int,
    min_breach_ratio: float,
    severity: str,
    channels: list[str],
    throttle_seconds: int,
) -> None:
    """Create-or-update a rule. Evaluator state (samples, last_fired_at,
    last_value) is NEVER touched here — that's owned by the evaluator."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO perf_alert_rules
                (id, name, enabled, module, instance_id, tag_key, tag_value,
                 metric, comparison, threshold,
                 window_seconds, min_breach_ratio,
                 severity, channels, throttle_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                enabled = EXCLUDED.enabled,
                module = EXCLUDED.module,
                instance_id = EXCLUDED.instance_id,
                tag_key = EXCLUDED.tag_key,
                tag_value = EXCLUDED.tag_value,
                metric = EXCLUDED.metric,
                comparison = EXCLUDED.comparison,
                threshold = EXCLUDED.threshold,
                window_seconds = EXCLUDED.window_seconds,
                min_breach_ratio = EXCLUDED.min_breach_ratio,
                severity = EXCLUDED.severity,
                channels = EXCLUDED.channels,
                throttle_seconds = EXCLUDED.throttle_seconds,
                updated_at = NOW()
            """,
            (rule_id, name, enabled, module, instance_id, tag_key, tag_value,
             metric, comparison, threshold,
             window_seconds, min_breach_ratio,
             severity, Jsonb(channels), throttle_seconds),
        )


def delete_perf_alert_rule(rule_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM perf_alert_rules WHERE id = %s", (rule_id,))


def update_perf_rule_state(
    rule_id: str,
    *,
    samples: list[dict[str, Any]],
    last_value: float | None,
    last_fired_at: datetime | None = None,
) -> None:
    """Evaluator-only. Updates the rolling sample buffer + last observed
    value. last_fired_at is updated only when an alert fires (left None
    here means 'don't touch')."""
    with get_pool().connection() as conn:
        if last_fired_at is not None:
            conn.execute(
                "UPDATE perf_alert_rules SET samples = %s, last_value = %s, "
                "last_fired_at = %s WHERE id = %s",
                (Jsonb(samples), last_value, last_fired_at, rule_id),
            )
        else:
            conn.execute(
                "UPDATE perf_alert_rules SET samples = %s, last_value = %s "
                "WHERE id = %s",
                (Jsonb(samples), last_value, rule_id),
            )


def list_unresolved_finding_ids_for_account(account: str) -> set[str]:
    """For scan-completion reconciliation: any open finding in this account
    that wasn't in the latest scan has been resolved."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT finding_id FROM posture_findings "
            "WHERE account = %s AND resolved_at IS NULL",
            (account,),
        ).fetchall()
    return {r[0] for r in rows}


# --- File Integrity Monitoring read-model -----------------------------------

def upsert_fim_baseline(
    instance_id: str,
    path: str,
    *,
    sha256: str,
    size: int,
    perm: int,
    owner_uid: int,
    owner_gid: int,
    mtime: datetime,
    last_seen_at: datetime,
) -> None:
    """Upsert the current known-good state for one path. `established_at` only
    gets set on insert (first time we ever saw this path) — subsequent updates
    leave it alone so the UI can show 'tracked since YYYY-MM-DD'."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO fim_baselines
                (instance_id, path, sha256, size, perm, owner_uid, owner_gid,
                 mtime, last_seen_at, established_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instance_id, path) DO UPDATE SET
                sha256 = EXCLUDED.sha256,
                size = EXCLUDED.size,
                perm = EXCLUDED.perm,
                owner_uid = EXCLUDED.owner_uid,
                owner_gid = EXCLUDED.owner_gid,
                mtime = EXCLUDED.mtime,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (instance_id, path, sha256, size, perm, owner_uid, owner_gid,
             mtime, last_seen_at, last_seen_at),
        )


def delete_fim_baseline(instance_id: str, path: str) -> None:
    """File was deleted. Drop the baseline row — history still records it."""
    with get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM fim_baselines WHERE instance_id = %s AND path = %s",
            (instance_id, path),
        )


def insert_fim_history(
    instance_id: str,
    path: str,
    *,
    changed_at: datetime,
    change_type: str,
    sha256_before: str | None,
    sha256_after: str | None,
    size_before: int | None,
    size_after: int | None,
    perm_before: int | None,
    perm_after: int | None,
    owner_before: str | None,
    owner_after: str | None,
    event_id: str | None,
    detection: str | None = None,
    actor_uid: int | None = None,
    actor_gid: int | None = None,
    actor_pid: int | None = None,
    actor_comm: str | None = None,
    actor_exe: str | None = None,
    actor_proctitle: str | None = None,
) -> None:
    """Append-only change log. One row per detected change. Actor fields
    are populated only when Part 3 auditd whodata had a fresh hit for
    this path; null otherwise."""
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO fim_history
                (instance_id, path, changed_at, change_type,
                 sha256_before, sha256_after, size_before, size_after,
                 perm_before, perm_after, owner_before, owner_after,
                 event_id, detection,
                 actor_uid, actor_gid, actor_pid,
                 actor_comm, actor_exe, actor_proctitle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (instance_id, path, changed_at, change_type,
             sha256_before, sha256_after, size_before, size_after,
             perm_before, perm_after, owner_before, owner_after,
             event_id, detection,
             actor_uid, actor_gid, actor_pid,
             actor_comm, actor_exe, actor_proctitle),
        )


def list_fim_history(instance_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Most recent changes on this host."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT path, changed_at, change_type,
                   sha256_before, sha256_after,
                   size_before, size_after,
                   perm_before, perm_after,
                   owner_before, owner_after,
                   event_id, detection,
                   actor_uid, actor_gid, actor_pid,
                   actor_comm, actor_exe, actor_proctitle
            FROM fim_history
            WHERE instance_id = %s
            ORDER BY changed_at DESC
            LIMIT %s
            """,
            (instance_id, limit),
        ).fetchall()
    return [
        {
            "path": r[0],
            "changed_at": r[1].isoformat() if r[1] else None,
            "change_type": r[2],
            "sha256_before": r[3],
            "sha256_after": r[4],
            "size_before": r[5],
            "size_after": r[6],
            "perm_before": r[7],
            "perm_after": r[8],
            "owner_before": r[9],
            "owner_after": r[10],
            "event_id": str(r[11]) if r[11] else None,
            "detection": r[12],
            "actor_uid": r[13],
            "actor_gid": r[14],
            "actor_pid": r[15],
            "actor_comm": r[16],
            "actor_exe": r[17],
            "actor_proctitle": r[18],
        }
        for r in rows
    ]


def count_fim_baselines(instance_id: str) -> int:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM fim_baselines WHERE instance_id = %s",
            (instance_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def upsert_fim_coverage(
    instance_id: str,
    *,
    paths_configured: int,
    files_tracked: int,
    last_full_scan_at: datetime | None,
    last_scan_duration_ms: int | None,
    scan_errors: int,
    updated_at: datetime,
    paths_inotify: int = 0,
    paths_baseline_only: int = 0,
    inotify_active: bool = False,
    inotify_watch_count: int = 0,
    auditd_active: bool = False,
    configured_paths: dict[str, Any] | None = None,
    path_stats: dict[str, Any] | None = None,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO fim_coverage
                (instance_id, paths_configured, files_tracked,
                 last_full_scan_at, last_scan_duration_ms, scan_errors,
                 updated_at, paths_inotify, paths_baseline_only,
                 inotify_active, inotify_watch_count,
                 auditd_active, configured_paths, path_stats)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instance_id) DO UPDATE SET
                paths_configured = EXCLUDED.paths_configured,
                files_tracked = EXCLUDED.files_tracked,
                last_full_scan_at = COALESCE(EXCLUDED.last_full_scan_at,
                                             fim_coverage.last_full_scan_at),
                last_scan_duration_ms = COALESCE(EXCLUDED.last_scan_duration_ms,
                                                 fim_coverage.last_scan_duration_ms),
                scan_errors = EXCLUDED.scan_errors,
                updated_at = EXCLUDED.updated_at,
                paths_inotify = EXCLUDED.paths_inotify,
                paths_baseline_only = EXCLUDED.paths_baseline_only,
                inotify_active = EXCLUDED.inotify_active,
                inotify_watch_count = EXCLUDED.inotify_watch_count,
                auditd_active = EXCLUDED.auditd_active,
                configured_paths = COALESCE(EXCLUDED.configured_paths,
                                            fim_coverage.configured_paths),
                path_stats = COALESCE(EXCLUDED.path_stats,
                                      fim_coverage.path_stats)
            """,
            (instance_id, paths_configured, files_tracked,
             last_full_scan_at, last_scan_duration_ms, scan_errors, updated_at,
             paths_inotify, paths_baseline_only,
             inotify_active, inotify_watch_count,
             auditd_active,
             Jsonb(configured_paths) if configured_paths is not None else None,
             Jsonb(path_stats) if path_stats is not None else None),
        )


def list_fim_hosts() -> list[dict[str, Any]]:
    """Every host that has FIM data, joined with the host_status row so we
    can show hostname / tags / liveness on the top-level FIM page. Ordered
    by most-recently-active first."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.instance_id,
                hs.hostname,
                hs.account,
                hs.region,
                hs.extra,
                hs.updated_at,
                c.files_tracked,
                c.paths_configured,
                c.last_full_scan_at,
                c.inotify_active,
                c.inotify_watch_count,
                c.auditd_active,
                c.updated_at AS coverage_updated_at,
                c.scan_errors
            FROM fim_coverage c
            LEFT JOIN host_status hs USING (instance_id)
            ORDER BY hs.updated_at DESC NULLS LAST, c.instance_id
            """
        ).fetchall()
    return [
        {
            "instance_id": r[0],
            "hostname": r[1],
            "account": r[2],
            "region": r[3],
            "tags": (r[4] or {}).get("tags") if isinstance(r[4], dict) else None,
            "host_updated_at": r[5].isoformat() if r[5] else None,
            "files_tracked": int(r[6]),
            "paths_configured": int(r[7]),
            "last_full_scan_at": r[8].isoformat() if r[8] else None,
            "inotify_active": bool(r[9]),
            "inotify_watch_count": int(r[10]),
            "auditd_active": bool(r[11]),
            "coverage_updated_at": r[12].isoformat() if r[12] else None,
            "scan_errors": int(r[13]),
        }
        for r in rows
    ]


def list_recent_fim_history(limit: int = 100) -> list[dict[str, Any]]:
    """Most-recent FIM changes across ALL hosts. Drives the cross-host
    activity table on the top-level FIM page."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT
                instance_id, path, changed_at, change_type,
                sha256_before, sha256_after,
                size_before, size_after,
                perm_before, perm_after,
                owner_before, owner_after,
                event_id, detection,
                actor_uid, actor_gid, actor_pid,
                actor_comm, actor_exe, actor_proctitle
            FROM fim_history
            ORDER BY changed_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "instance_id": r[0],
            "path": r[1],
            "changed_at": r[2].isoformat() if r[2] else None,
            "change_type": r[3],
            "sha256_before": r[4],
            "sha256_after": r[5],
            "size_before": r[6],
            "size_after": r[7],
            "perm_before": r[8],
            "perm_after": r[9],
            "owner_before": r[10],
            "owner_after": r[11],
            "event_id": str(r[12]) if r[12] else None,
            "detection": r[13],
            "actor_uid": r[14],
            "actor_gid": r[15],
            "actor_pid": r[16],
            "actor_comm": r[17],
            "actor_exe": r[18],
            "actor_proctitle": r[19],
        }
        for r in rows
    ]


def list_fim_baselines(instance_id: str) -> list[dict[str, Any]]:
    """Every file we've baselined on this host. Used by the per-instance
    page to compute file-counts-per-directory."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT path, sha256, size, perm, owner_uid, owner_gid, last_seen_at "
            "FROM fim_baselines WHERE instance_id = %s ORDER BY path",
            (instance_id,),
        ).fetchall()
    return [
        {
            "path": r[0],
            "sha256": r[1],
            "size": int(r[2]),
            "perm": int(r[3]),
            "owner_uid": int(r[4]),
            "owner_gid": int(r[5]),
            "last_seen_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


def get_fim_coverage(instance_id: str) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT paths_configured, files_tracked, last_full_scan_at,
                   last_scan_duration_ms, scan_errors, updated_at,
                   paths_inotify, paths_baseline_only,
                   inotify_active, inotify_watch_count,
                   auditd_active, configured_paths, path_stats
            FROM fim_coverage WHERE instance_id = %s
            """,
            (instance_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "paths_configured": int(row[0]),
        "files_tracked": int(row[1]),
        "last_full_scan_at": row[2].isoformat() if row[2] else None,
        "last_scan_duration_ms": int(row[3]) if row[3] is not None else None,
        "scan_errors": int(row[4]),
        "updated_at": row[5].isoformat() if row[5] else None,
        "paths_inotify": int(row[6]),
        "paths_baseline_only": int(row[7]),
        "inotify_active": bool(row[8]),
        "inotify_watch_count": int(row[9]),
        "auditd_active": bool(row[10]),
        "configured_paths": row[11] if row[11] else None,
        "path_stats": row[12] if row[12] else None,
    }


# --- RDS sessions ------------------------------------------------------------

_RDS_SESSION_COLS = (
    "session_id, db_instance, source_type, db_user, db_name, "
    "source_ip, source_port, connected_at, last_seen_at, "
    "disconnected_at, duration_seconds, extra"
)


def _rds_session_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "session_id": row[0], "db_instance": row[1], "source_type": row[2],
        "db_user": row[3], "db_name": row[4],
        "source_ip": row[5], "source_port": row[6],
        "connected_at": row[7], "last_seen_at": row[8],
        "disconnected_at": row[9], "duration_seconds": row[10],
        "extra": row[11] or {},
    }


def upsert_rds_session_start(
    session_id: str, *, db_instance: str, source_type: str,
    db_user: str | None, db_name: str | None,
    source_ip: str | None, source_port: int | None,
    connected_at: datetime, extra: dict[str, Any] | None,
) -> bool:
    """Insert an active session. Returns True if new, False if we already had
    this session_id (which happens under log replay / restart)."""
    with get_pool().connection() as conn:
        row = conn.execute(
            f"""
            INSERT INTO rds_active_sessions
              (session_id, db_instance, source_type, db_user, db_name,
               source_ip, source_port, connected_at, last_seen_at, extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE
              SET last_seen_at = EXCLUDED.last_seen_at
            RETURNING (xmax = 0) AS inserted
            """,
            (session_id, db_instance, source_type, db_user, db_name,
             source_ip, source_port, connected_at, connected_at,
             Jsonb(extra or {})),
        ).fetchone()
    return bool(row and row[0])


def close_rds_session(
    session_id: str, *, disconnected_at: datetime,
    duration_seconds: int | None,
) -> bool:
    """Mark a session ended. Returns True if the row existed + was open."""
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE rds_active_sessions
               SET disconnected_at = %s,
                   duration_seconds = COALESCE(%s, duration_seconds,
                                       EXTRACT(EPOCH FROM (%s - connected_at))::INT),
                   last_seen_at = %s
             WHERE session_id = %s AND disconnected_at IS NULL
             RETURNING session_id
            """,
            (disconnected_at, duration_seconds, disconnected_at,
             disconnected_at, session_id),
        ).fetchone()
    return row is not None


def list_rds_active_sessions(
    db_instance: str | None = None, limit: int = 500,
) -> list[dict[str, Any]]:
    sql = (
        f"SELECT {_RDS_SESSION_COLS} FROM rds_active_sessions "
        f"WHERE disconnected_at IS NULL"
    )
    args: tuple[Any, ...] = ()
    if db_instance is not None:
        sql += " AND db_instance = %s"; args = (db_instance,)
    sql += " ORDER BY connected_at DESC LIMIT %s"
    args = args + (limit,)
    with get_pool().connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_rds_session_row(r) for r in rows]


def list_rds_recent_sessions(
    db_instance: str | None = None, db_user: str | None = None,
    since: datetime | None = None, limit: int = 500,
) -> list[dict[str, Any]]:
    """Recent sessions including closed ones — used by the history page."""
    sql = f"SELECT {_RDS_SESSION_COLS} FROM rds_active_sessions WHERE 1=1"
    args: list[Any] = []
    if db_instance is not None:
        sql += " AND db_instance = %s"; args.append(db_instance)
    if db_user is not None:
        sql += " AND db_user = %s"; args.append(db_user)
    if since is not None:
        sql += " AND connected_at >= %s"; args.append(since)
    sql += " ORDER BY connected_at DESC LIMIT %s"
    args.append(limit)
    with get_pool().connection() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [_rds_session_row(r) for r in rows]


def list_rds_db_instances() -> list[dict[str, Any]]:
    """Distinct DBs we've seen sessions for, with live-connection counts."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT db_instance, source_type,
                   COUNT(*) FILTER (WHERE disconnected_at IS NULL) AS active,
                   COUNT(*)                                        AS total_seen,
                   MAX(last_seen_at)                               AS last_activity
              FROM rds_active_sessions
             GROUP BY db_instance, source_type
             ORDER BY db_instance
            """
        ).fetchall()
    return [
        {"db_instance": r[0], "source_type": r[1],
         "active": int(r[2]), "total_seen": int(r[3]),
         "last_activity": r[4]}
        for r in rows
    ]

