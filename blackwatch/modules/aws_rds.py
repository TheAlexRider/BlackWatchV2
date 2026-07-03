"""AWS RDS log adapter.

Consumes payloads from the BW CloudWatch-Logs forwarder Lambda. Each SQS
message is one CloudWatch Logs batch, shaped as:

    {
      "log_group":   "/aws/rds/instance/<db>/postgresql",
      "log_stream":  "<db>.0",
      "db_instance": "<db>",                    # derived by the Lambda
      "source_type": "postgres" | "rds_proxy",  # derived by the Lambda
      "events":      [ {"ts": <ms>, "message": "..."} ]
    }

We emit normalized actions:

  * rds.session.start     — successful connection (from `LOG: connection authorized`)
  * rds.session.end       — client disconnected (from `LOG: disconnection`)
  * rds.auth.failure      — bad credentials / hba mismatch (from FATAL/proxy auth failed)
  * rds.error             — engine-side errors (schema mismatch, deadlock, etc.)
  * rds.query.ddl / rds.query.role / rds.query.misc — pgaudit-decoded rows

The projection turns session.start/end into rows in rds_active_sessions. This
adapter is pure — it never touches the DB directly.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor, Category, Event, Observable, Outcome, Source, Target, Transport,
)
from .base import Adapter, IngestContext

_MODULE = "aws.rds"

# AWS-managed system users. These accounts belong to RDS's control plane
# (health checks, backups, replication, monitoring). They connect ~every
# minute forever, are not human-driven, and can never be an attacker. We
# suppress session.start / session.end events for them so the dashboard
# stays focused on real activity.
#
# Auth failures for these users ARE kept -- an attacker attempting to
# authenticate as rdsadmin is a real signal (even though it can't succeed).
_SYSTEM_USERS = frozenset({
    "rdsadmin",
    "rdsproxyadmin",
    "rds_superuser",
    "rds_iam_authorization",
    "rdssecadmin",
    "rds_replication",
    "rds_monitor",
})


def _is_system_user(name: str | None) -> bool:
    if not name:
        return False
    return name in _SYSTEM_USERS

# --- Postgres log line patterns ----------------------------------------------
# RDS default log_line_prefix is: %t:%r:%u@%d:[%p]:
#   %t = timestamp                 e.g. "2026-06-30 12:34:56 UTC"
#   %r = remote host and port      e.g. "172.17.4.55(45678)"  or "[local]"
#   %u = user name                 e.g. "alice"
#   %d = database name             e.g. "myapp"
#   %p = pid                       e.g. "12345"
# Followed by ":" then severity + message.

_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*(?:UTC|Z)?):"
    r"(?P<remote>[^:]*):"
    r"(?P<user>[^@:]*)@(?P<db>[^:]*):"
    r"\[(?P<pid>\d+)\]:"
    r"(?P<sev>[A-Z]+):\s*"
    r"(?P<msg>.*)$"
)

# Postgres log messages we care about.
_CONNECT_AUTHZ = re.compile(
    r"connection authorized:\s*user=(?P<user>\S+)\s+database=(?P<db>\S+)"
)
_DISCONNECT = re.compile(
    r"disconnection:\s*session time:\s*"
    r"(?P<h>\d+):(?P<m>\d+):(?P<s>\d+(?:\.\d+)?)\s*"
    r"user=(?P<user>\S+)\s+database=(?P<db>\S+)\s+host=(?P<host>\S+)"
)
_AUTH_FAIL = re.compile(
    r"password authentication failed for user \"(?P<user>[^\"]+)\""
)
_HBA_REJECT = re.compile(
    r"no pg_hba\.conf entry for host \"(?P<host>[^\"]+)\","
    r"(?:\s*user \"(?P<user>[^\"]+)\",)?"
)
_REMOTE_ADDR = re.compile(r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\((?P<port>\d+)\)$")

# --- pgaudit decoder ---------------------------------------------------------
# pgaudit format:
#   AUDIT: SESSION,<audit_id>,<sub_id>,<class>,<command>,<object_type>,<object_name>,<stmt>[,<params>]
_PGAUDIT = re.compile(r"^AUDIT:\s*(?P<scope>SESSION|OBJECT),(?P<rest>.*)$")

# --- RDS Proxy log line pattern ---------------------------------------------
# Example:
#   2026-06-26T16:55:27.150Z [INFO] [proxyEndpoint=default] [clientConnection=2383522377]
#     Proxy authentication with PostgreSQL native password authentication failed for user "X" ...
_PROXY_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+"
    r"\[(?P<level>[A-Z]+)\]\s+"
    r"(?P<tags>(?:\[[^\]]+\]\s*)+)"
    r"(?P<msg>.*)$"
)
_PROXY_TAG = re.compile(r"\[(?P<k>[^=]+)=(?P<v>[^\]]+)\]")
_PROXY_AUTH_FAIL = re.compile(
    r"[Pp]roxy authentication.*failed for user \"(?P<user>[^\"]+)\""
)


class AwsRdsAdapter(Adapter):
    module = _MODULE

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict):
            return []
        events_in = raw.get("events") or []
        if not events_in:
            return []
        db_instance = raw.get("db_instance") or "unknown"
        source_type = raw.get("source_type") or "postgres"

        try:
            transport = Transport(ctx.transport)
        except ValueError:
            transport = Transport.queue

        out: list[Event] = []
        for entry in events_in:
            message = entry.get("message") if isinstance(entry, dict) else None
            if not message:
                continue
            ts = _parse_ts(entry.get("ts"))
            if source_type == "rds_proxy":
                ev = self._parse_proxy_line(message, ts, db_instance, transport)
            else:
                ev = self._parse_postgres_line(message, ts, db_instance, transport)
            if ev is not None:
                out.append(ev)
        return out

    # ---- Postgres --------------------------------------------------------

    def _parse_postgres_line(
        self, line: str, ts: datetime, db_instance: str, transport: Transport,
    ) -> Event | None:
        prefix = _PREFIX.match(line)
        if not prefix:
            return None
        pid = prefix.group("pid")
        remote = prefix.group("remote") or ""
        prefix_user = prefix.group("user") or None
        prefix_db = prefix.group("db") or None
        msg = prefix.group("msg") or ""
        sev = prefix.group("sev") or ""
        src_ip, src_port = _split_remote(remote)

        session_key = f"{db_instance}|pid={pid}|since={ts.isoformat()}"

        m = _CONNECT_AUTHZ.search(msg)
        if m:
            user = m.group("user")
            db = m.group("db")
            if _is_system_user(user):
                return None                    # AWS control-plane chatter -- skip
            return _mkevent(
                action="rds.session.start",
                outcome=Outcome.success,
                ts=ts, db_instance=db_instance, source_type="postgres",
                user=user, db=db, src_ip=src_ip, src_port=src_port,
                session_id=_session_id(db_instance, pid),
                extra={
                    "backend_pid": pid,
                    "session_key": session_key,
                },
                transport=transport,
            )

        m = _DISCONNECT.search(msg)
        if m:
            user = m.group("user")
            db = m.group("db")
            if _is_system_user(user):
                return None                    # same suppression as .start
            duration = int(int(m.group("h")) * 3600 + int(m.group("m")) * 60 + float(m.group("s")))
            return _mkevent(
                action="rds.session.end",
                outcome=Outcome.success,
                ts=ts, db_instance=db_instance, source_type="postgres",
                user=user, db=db, src_ip=src_ip, src_port=src_port,
                session_id=_session_id(db_instance, pid),
                extra={
                    "backend_pid": pid,
                    "duration_seconds": duration,
                    "host": m.group("host"),
                },
                transport=transport,
            )

        m = _AUTH_FAIL.search(msg)
        if m:
            return _mkevent(
                action="rds.auth.failure",
                outcome=Outcome.failure,
                ts=ts, db_instance=db_instance, source_type="postgres",
                user=m.group("user"), db=prefix_db,
                src_ip=src_ip, src_port=src_port,
                session_id=None,
                extra={"reason": "invalid_password", "backend_pid": pid},
                transport=transport,
            )

        m = _HBA_REJECT.search(msg)
        if m:
            return _mkevent(
                action="rds.auth.failure",
                outcome=Outcome.failure,
                ts=ts, db_instance=db_instance, source_type="postgres",
                user=m.group("user") or prefix_user,
                db=prefix_db,
                src_ip=src_ip or m.group("host"),
                src_port=src_port,
                session_id=None,
                extra={"reason": "no_pg_hba_entry", "backend_pid": pid},
                transport=transport,
            )

        # pgaudit lines look like: AUDIT: SESSION,<audit_id>,<sub>,<class>,<cmd>,...
        m = _PGAUDIT.search(msg)
        if m:
            fields = _split_pgaudit(m.group("rest"))
            cls = (fields[2] if len(fields) > 2 else "").upper() or "MISC"
            cmd = (fields[3] if len(fields) > 3 else "") or ""
            stmt = (fields[7] if len(fields) > 7 else "") or ""
            action = _pgaudit_action(cls)
            return _mkevent(
                action=action,
                outcome=Outcome.success,
                ts=ts, db_instance=db_instance, source_type="postgres",
                user=prefix_user, db=prefix_db,
                src_ip=src_ip, src_port=src_port,
                session_id=_session_id(db_instance, pid),
                extra={
                    "backend_pid": pid,
                    "audit_class": cls,
                    "command": cmd,
                    "statement": (stmt[:500] if stmt else None),
                    "scope": m.group("scope"),
                },
                transport=transport,
            )

        # Anything else with FATAL severity is worth surfacing as rds.error.
        if sev in ("FATAL", "PANIC"):
            return _mkevent(
                action="rds.error",
                outcome=Outcome.failure,
                ts=ts, db_instance=db_instance, source_type="postgres",
                user=prefix_user, db=prefix_db,
                src_ip=src_ip, src_port=src_port,
                session_id=None,
                extra={"severity": sev, "message": msg[:500]},
                transport=transport,
            )
        return None

    # ---- RDS Proxy -------------------------------------------------------

    def _parse_proxy_line(
        self, line: str, ts: datetime, db_instance: str, transport: Transport,
    ) -> Event | None:
        m = _PROXY_PREFIX.match(line)
        if not m:
            return None
        tags = {t.group("k"): t.group("v") for t in _PROXY_TAG.finditer(m.group("tags"))}
        msg = m.group("msg") or ""
        conn_id = tags.get("clientConnection")

        auth = _PROXY_AUTH_FAIL.search(msg)
        if auth:
            return _mkevent(
                action="rds.auth.failure",
                outcome=Outcome.failure,
                ts=ts, db_instance=db_instance, source_type="rds_proxy",
                user=auth.group("user"), db=None,
                src_ip=None, src_port=None,
                session_id=None,
                extra={
                    "reason": "invalid_credentials",
                    "proxy_endpoint": tags.get("proxyEndpoint"),
                    "client_connection": conn_id,
                    "message": msg[:300],
                },
                transport=transport,
            )
        return None


# --- helpers ----------------------------------------------------------------

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f UTC", "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _split_remote(remote: str) -> tuple[str | None, int | None]:
    m = _REMOTE_ADDR.match(remote)
    if m:
        return m.group("ip"), int(m.group("port"))
    return None, None


def _split_pgaudit(rest: str) -> list[str]:
    # pgaudit fields are comma-separated but statements can contain commas;
    # commas inside double-quoted fields don't count. Cheap CSV parse:
    fields: list[str] = []
    buf: list[str] = []
    in_q = False
    i = 0
    while i < len(rest):
        c = rest[i]
        if c == '"':
            if in_q and i + 1 < len(rest) and rest[i + 1] == '"':
                buf.append('"'); i += 2; continue
            in_q = not in_q
        elif c == "," and not in_q:
            fields.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    fields.append("".join(buf))
    return fields


def _pgaudit_action(cls: str) -> str:
    cls = cls.upper()
    if cls == "DDL":  return "rds.query.ddl"
    if cls == "ROLE": return "rds.query.role"
    if cls == "READ": return "rds.query.read"
    if cls == "WRITE": return "rds.query.write"
    if cls == "FUNCTION": return "rds.query.function"
    return "rds.query.misc"


def _session_id(db_instance: str, pid: str) -> str:
    return f"pg:{db_instance}:{pid}"


def _mkevent(
    *, action: str, outcome: Outcome, ts: datetime,
    db_instance: str, source_type: str,
    user: str | None, db: str | None,
    src_ip: str | None, src_port: int | None,
    session_id: str | None,
    extra: dict[str, Any], transport: Transport,
) -> Event:
    observables: list[Observable] = []
    if src_ip:
        observables.append(Observable(type="ip", value=src_ip))
    if user:
        observables.append(Observable(type="user", value=user))
    tags = {"env": "prod", "db_instance": db_instance,
            "source": source_type}
    if db:
        tags["database"] = db
    payload = {
        "db_instance": db_instance,
        "source_type": source_type,
        "user": user,
        "database": db,
        "source_ip": src_ip,
        "source_port": src_port,
        **extra,
    }
    if session_id:
        payload["session_id"] = session_id
    # Deterministic event_id so log-replay / at-least-once SQS delivery dedupes.
    fp_src = f"{action}|{db_instance}|{ts.isoformat()}|{session_id or ''}|{user or ''}|{src_ip or ''}"
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, fp_src))
    return Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=transport),
        event_time=ts,
        category=Category.other,
        action=action,
        outcome=outcome,
        actor=Actor(principal=user, source_ip=src_ip),
        target=Target(id=db_instance, type="rds.db", name=db_instance),
        observables=observables,
        extra={**payload, "tags": tags},
        raw={"module": _MODULE, "session_id": session_id},
    )
