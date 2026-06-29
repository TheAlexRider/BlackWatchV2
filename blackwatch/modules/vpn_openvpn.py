"""OpenVPN (Community Edition) adapter.

Consumes payloads from the on-host push agent (`scripts/vpn_agent.py`), which
drain via SQS:

  * Periodic heartbeat (kind="vpn_report"):
      {server, host:{instance_id,…}, agent_version, uptime_seconds,
       state, active, status_raw, auth_lines}
  * Sub-second real-time auth burst (kind="vpn_auth_realtime"):
      {server, host, auth_lines}   # only auth_lines populated

The adapter is shape-tolerant — it never branches on `kind`. Whichever fields
are present produce their corresponding events; missing fields produce nothing.
That's what lets the same code handle both the slow heartbeat and the fast
follower batches with no special-casing.

Emits:
  * vpn.service.health   — outcome=success when active, failure otherwise
  * vpn.status.snapshot  — the currently-connected client set (in `extra.clients`)
  * vpn.auth.success / vpn.auth.failure — one per matched journal line, with a
    deterministic event_id derived from __CURSOR so overlapping windows / dual
    feeds (during the SSH→agent cutover) dedup on insert.

This adapter is PURE: it parses, it does not diff against history or touch the
DB. Stateful work (who-just-connected, the live read-model) happens in the VPN
projection (blackwatch/vpn/projection.py), fed by the snapshot event.

The status-file parser handles status-version 1 (the default human CSV format,
which is what the current server runs) as well as the machine-readable v2
(comma) and v3 (tab) formats, so upgrading the server doesn't break parsing.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor,
    Category,
    Event,
    Observable,
    Outcome,
    Source,
    Target,
    Transport,
)
from .base import Adapter, IngestContext

# Cert expiry bands — same shape as the generic cert_probe adapter. Returns
# the action to emit, or None if the cert is healthy / not worth an event.
# Revoked certs are noted on the snapshot but don't fire expiry events.
def _cert_action(cert: dict) -> str | None:
    if cert.get("error"):
        return "vpn.cert.probe.failed"
    if cert.get("revoked"):
        return None
    days = cert.get("days_remaining")
    if days is None:
        return "vpn.cert.probe.failed"
    if days < 0:
        return "vpn.cert.expired"
    if days < 7:
        return "vpn.cert.expiring.critical"
    if days < 14:
        return "vpn.cert.expiring.high"
    if days < 30:
        return "vpn.cert.expiring.warning"
    return None


# Auth-line patterns from the OpenVPN journal.
_AUTH_IP = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):\d+")
_AUTH_FAIL = re.compile(r"SENT CONTROL \[([^\]]+)\]: 'AUTH_FAILED'")
_AUTH_OK = re.compile(r"authentication succeeded for username '([^']+)'")

# Field order of CLIENT_LIST rows in status-version 2/3 (after the leading
# "CLIENT_LIST" record-type token).
_MACHINE_FIELDS = [
    "common_name",
    "real_address",
    "virtual_address",
    "virtual_ipv6",
    "bytes_received",
    "bytes_sent",
    "connected_since",
    "connected_since_t",
    "username",
    "client_id",
    "peer_id",
    "data_channel_cipher",
]


def _real_ip(real_address: str | None) -> str | None:
    if not real_address:
        return None
    # IPv4 "1.2.3.4:port" or IPv6 "[2001:db8::1]:port" / "2001:db8::1:port"
    host = real_address.rsplit(":", 1)[0]
    return host.strip("[]") or None


def _parse_machine(client_lines: list[str], sep: str) -> list[dict[str, Any]]:
    clients: list[dict[str, Any]] = []
    for line in client_lines:
        parts = line.split(sep)[1:]  # drop the "CLIENT_LIST" token
        client = {name: (parts[i] if i < len(parts) else None) for i, name in enumerate(_MACHINE_FIELDS)}
        client["real_ip"] = _real_ip(client.get("real_address"))
        clients.append(client)
    return clients


def _parse_v1(lines: list[str]) -> list[dict[str, Any]]:
    clients: list[dict[str, Any]] = []
    virtual_by_cn: dict[str, str] = {}

    # Section 1: CLIENT LIST
    in_clients = False
    for line in lines:
        if line.startswith("Common Name,Real Address"):
            in_clients = True
            continue
        if in_clients:
            if not line.strip() or line.startswith(("ROUTING TABLE", "GLOBAL STATS", "END")):
                in_clients = False
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            real_address = parts[1]
            clients.append(
                {
                    "common_name": parts[0],
                    "real_address": real_address,
                    "real_ip": _real_ip(real_address),
                    "bytes_received": parts[2],
                    "bytes_sent": parts[3],
                    "connected_since": ",".join(parts[4:]),
                    "username": None,
                    "virtual_address": None,
                }
            )

    # Section 2: ROUTING TABLE -> map virtual address back onto clients by CN
    in_routes = False
    for line in lines:
        if line.startswith("Virtual Address,Common Name"):
            in_routes = True
            continue
        if in_routes:
            if not line.strip() or line.startswith(("GLOBAL STATS", "END")):
                in_routes = False
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                virtual_by_cn.setdefault(parts[1], parts[0])
    for client in clients:
        if client.get("common_name") in virtual_by_cn:
            client["virtual_address"] = virtual_by_cn[client["common_name"]]

    return clients


def parse_status(text: str) -> list[dict[str, Any]]:
    """Parse OpenVPN status output (any version) into a list of client dicts."""
    if not text:
        return []
    lines = text.splitlines()
    client_lines = [ln for ln in lines if ln.startswith("CLIENT_LIST")]
    if client_lines:
        sep = "\t" if "\t" in client_lines[0] else ","
        return _parse_machine(client_lines, sep)
    return _parse_v1(lines)


def _journal_message(entry: dict[str, Any]) -> str:
    msg = entry.get("MESSAGE", "")
    if isinstance(msg, list):  # journald returns non-UTF8 messages as byte arrays
        try:
            return bytes(msg).decode("utf-8", "replace")
        except Exception:
            return ""
    return msg or ""


def _journal_time(entry: dict[str, Any]) -> datetime:
    ts = entry.get("__REALTIME_TIMESTAMP")
    try:
        return datetime.fromtimestamp(int(ts) / 1_000_000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def parse_auth_lines(lines: list, server: str, account: str | None = None) -> list[Event]:
    """Turn journalctl --output=json auth lines into vpn.auth.* events. The
    event_id is derived from the journal cursor so re-reading overlapping
    windows never creates duplicates (ON CONFLICT dedup on insert)."""
    events: list[Event] = []
    for line in lines:
        if isinstance(line, dict):
            entry = line
        else:
            try:
                entry = json.loads(line)
            except (ValueError, TypeError):
                continue

        message = _journal_message(entry)
        ip_match = _AUTH_IP.search(message)
        source_ip = ip_match.group(1) if ip_match else None

        if "AUTH_FAILED" in message:
            user_match = _AUTH_FAIL.search(message)
            if not user_match:
                continue
            user, action, outcome = user_match.group(1), "vpn.auth.failure", Outcome.failure
        elif "authentication succeeded for username" in message:
            user_match = _AUTH_OK.search(message)
            if not user_match:
                continue
            user, action, outcome = user_match.group(1), "vpn.auth.success", Outcome.success
        else:
            continue

        cursor = entry.get("__CURSOR") or f"{entry.get('__REALTIME_TIMESTAMP', '')}{message}"
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vpn-auth:{cursor}"))
        observables = []
        if source_ip:
            observables.append(Observable(type="ip", value=source_ip))
        if user:
            observables.append(Observable(type="user", value=user))

        events.append(
            Event(
                event_id=event_id,
                source=Source(module="vpn.openvpn", transport=Transport.poll, account=account),
                event_time=_journal_time(entry),
                category=Category.vpn,
                action=action,
                outcome=outcome,
                actor=Actor(principal=user, source_ip=source_ip),
                target=Target(id=server, type="vpn.server", name=server),
                observables=observables,
                extra={
                    "server": server,
                    "log_line": message,
                    # Friendly headline for Slack/Discord/etc. Templates already
                    # append "— {actor.principal} from {source_ip} on {target}"
                    # after this string, so we just describe WHAT happened.
                    "message": (
                        "VPN authentication FAILED"
                        if outcome == Outcome.failure
                        else "VPN login"
                    ),
                },
                raw=entry,
            )
        )
    return events


class VpnOpenVpnAdapter(Adapter):
    module = "vpn.openvpn"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        body: dict[str, Any] = raw if isinstance(raw, dict) else {}
        server = body.get("server") or ctx.account or "openvpn"
        host_info = body.get("host") or {}
        # Push agent ships richer host context; SSH-pull leaves these None.
        account = host_info.get("account") or ctx.account
        region = host_info.get("region") or ctx.region
        # Map IngestContext.transport to the enum (queue for push agent,
        # poll for the legacy SSH pull).
        try:
            transport = Transport(ctx.transport)
        except ValueError:
            transport = Transport.poll
        now = datetime.now(timezone.utc)
        events: list[Event] = []

        def src() -> Source:
            return Source(module=self.module, transport=transport, account=account, region=region)

        def base_target() -> Target:
            return Target(id=server, type="vpn.server", name=server)

        # 1) Service health
        if "active" in body or "state" in body:
            active = bool(body["active"]) if "active" in body else body.get("state") == "active"
            health_extra: dict[str, Any] = {"server": server, "state": body.get("state")}
            # Push-agent heartbeat metadata (omitted for SSH-pull payloads).
            if body.get("agent_version"):
                health_extra["agent_version"] = body["agent_version"]
            if body.get("uptime_seconds") is not None:
                health_extra["uptime_seconds"] = body["uptime_seconds"]
            if host_info.get("instance_id"):
                health_extra["instance_id"] = host_info["instance_id"]
            if host_info.get("hostname"):
                health_extra["hostname"] = host_info["hostname"]
            events.append(
                Event(
                    source=src(),
                    event_time=now,
                    category=Category.vpn,
                    action="vpn.service.health",
                    outcome=Outcome.success if active else Outcome.failure,
                    target=base_target(),
                    extra=health_extra,
                    raw=raw,
                )
            )

        # 2) Currently-connected snapshot
        if body.get("status_raw") is not None:
            clients = parse_status(body["status_raw"])
            observables: list[Observable] = []
            seen: set[tuple[str, str]] = set()
            for client in clients:
                if client.get("real_ip") and ("ip", client["real_ip"]) not in seen:
                    observables.append(Observable(type="ip", value=client["real_ip"]))
                    seen.add(("ip", client["real_ip"]))
                identity = client.get("username") or client.get("common_name")
                if identity and ("user", identity) not in seen:
                    observables.append(Observable(type="user", value=identity))
                    seen.add(("user", identity))
            events.append(
                Event(
                    source=src(),
                    event_time=now,
                    category=Category.vpn,
                    action="vpn.status.snapshot",
                    outcome=Outcome.success,
                    target=base_target(),
                    observables=observables,
                    extra={"server": server, "client_count": len(clients), "clients": clients},
                    raw=raw,
                )
            )

        # 3) Auth attempts from the journal (successes + failures)
        events.extend(parse_auth_lines(body.get("auth_lines") or [], server, account))

        # 4) Cert inventory snapshot — list of {kind, name, subject, not_after,
        # days_remaining, ...}. One snapshot event drives the projection;
        # additional per-cert events fire when an individual cert is concerning
        # so they show up in /events and through the rules pipeline.
        certs = body.get("certs")
        if isinstance(certs, list):
            events.append(
                Event(
                    source=src(),
                    event_time=now,
                    category=Category.vpn,
                    action="vpn.cert.snapshot",
                    outcome=Outcome.success,
                    target=base_target(),
                    extra={"server": server, "certs": certs, "count": len(certs)},
                    raw=raw,
                )
            )
            for c in certs:
                action = _cert_action(c)
                if action is None:
                    continue
                cert_name = c.get("name") or "unknown"
                # Deterministic id so the same (cert, band) doesn't insert
                # twice across heartbeats. A band transition (e.g. high→critical
                # or a renewal back to healthy and out again) produces a new
                # id, so transitions DO surface.
                event_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"vpn-cert:{server}:{c.get('source','?')}:{c.get('kind','?')}:{cert_name}:{action}",
                ))
                events.append(
                    Event(
                        event_id=event_id,
                        source=src(),
                        event_time=now,
                        category=Category.vpn,
                        action=action,
                        outcome=Outcome.success if action != "vpn.cert.probe.failed" else Outcome.failure,
                        target=Target(
                            id=f"{server}/{cert_name}",
                            type=f"vpn.cert.{c.get('kind', 'unknown')}",
                            name=cert_name,
                        ),
                        extra={
                            "server": server,
                            "kind": c.get("kind"),
                            "source": c.get("source"),
                            "subject": c.get("subject"),
                            "issuer": c.get("issuer"),
                            "not_after": c.get("not_after"),
                            "days_remaining": c.get("days_remaining"),
                            "path": c.get("path"),
                            "error": c.get("error"),
                            "revoked": c.get("revoked", False),
                        },
                        raw=c,
                    )
                )

        return events
