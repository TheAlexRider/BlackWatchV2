"""VPN state projection.

This is the stateful counterpart to the (pure) OpenVPN adapter. It consumes
vpn.* events and:
  * maintains the live read-model (latest service state + connected clients per
    server) used by GET /vpn/status, and
  * derives new events by comparing snapshots over time:
      - vpn.session.start      a client appeared since the last snapshot
      - vpn.session.end        a client disappeared since the last snapshot
      - vpn.session.concurrent the same identity is connected from >1 IP at once

The derived events are returned to the caller (the ingest path), which scores
them with the rule engine and routes them like any other event. The first
snapshot for a server only establishes a baseline — it does not emit start/end,
to avoid a burst on startup.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
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

_MODULE = "vpn.openvpn"


def _session_key(client: dict[str, Any]) -> str:
    return f"{client.get('common_name')}|{client.get('real_address')}"


def _identity(client: dict[str, Any]) -> str | None:
    return client.get("username") or client.get("common_name")


def _derived_event(
    action: str,
    server: str,
    *,
    principal: str | None = None,
    source_ip: str | None = None,
    observables: list[Observable] | None = None,
    extra: dict[str, Any] | None = None,
    when: datetime,
) -> Event:
    return Event(
        source=Source(module=_MODULE, transport=Transport.poll),
        event_time=when,
        category=Category.vpn,
        action=action,
        outcome=Outcome.success,
        actor=Actor(principal=principal, source_ip=source_ip),
        target=Target(id=server, type="vpn.server", name=server),
        observables=observables or [],
        extra={"server": server, "derived": True, **(extra or {})},
        raw={"derived_from": "vpn.status.snapshot", "server": server},
    )


def detect_concurrent(server: str, clients: list[dict[str, Any]], when: datetime) -> list[Event]:
    by_identity: dict[str, set[str]] = {}
    for client in clients:
        identity = _identity(client)
        ip = client.get("real_ip")
        if identity and ip:
            by_identity.setdefault(identity, set()).add(ip)
    events: list[Event] = []
    for identity, ips in by_identity.items():
        if len(ips) > 1:
            events.append(
                _derived_event(
                    "vpn.session.concurrent",
                    server,
                    principal=identity,
                    observables=[Observable(type="ip", value=ip) for ip in sorted(ips)],
                    extra={"identity": identity, "source_ips": sorted(ips)},
                    when=when,
                )
            )
    return events


def diff_sessions(
    server: str,
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    when: datetime,
) -> list[Event]:
    prev_by_key = {_session_key(c): c for c in previous}
    cur_by_key = {_session_key(c): c for c in current}
    events: list[Event] = []

    for key, client in cur_by_key.items():
        if key not in prev_by_key:
            events.append(
                _derived_event(
                    "vpn.session.start",
                    server,
                    principal=_identity(client),
                    source_ip=client.get("real_ip"),
                    observables=_obs(client),
                    extra={"common_name": client.get("common_name")},
                    when=when,
                )
            )
    for key, client in prev_by_key.items():
        if key not in cur_by_key:
            events.append(
                _derived_event(
                    "vpn.session.end",
                    server,
                    principal=_identity(client),
                    source_ip=client.get("real_ip"),
                    observables=_obs(client),
                    extra={"common_name": client.get("common_name")},
                    when=when,
                )
            )
    return events


def _service_transition(prev_active, new_active) -> str | None:
    """Return the transition event name when service state changed, else None."""
    if prev_active is None and new_active:
        return "vpn.service.up"            # first-ever heartbeat
    if prev_active is True and not new_active:
        return "vpn.service.down"          # was up -> now down
    if prev_active is False and new_active:
        return "vpn.service.up"            # recovered from down
    return None


def _obs(client: dict[str, Any]) -> list[Observable]:
    out: list[Observable] = []
    if client.get("real_ip"):
        out.append(Observable(type="ip", value=client["real_ip"]))
    identity = _identity(client)
    if identity:
        out.append(Observable(type="user", value=identity))
    return out


def project(event: Event) -> list[Event]:
    """Update the read-model from a vpn.* event and return any derived events."""
    if event.source.module != _MODULE:
        return []
    server = event.target.id or event.extra.get("server") or "openvpn"
    when = event.event_time or datetime.now(timezone.utc)

    if event.action == "vpn.service.health":
        prev_row = storage.get_vpn_status(server)
        prev_active = prev_row["active"] if prev_row else None
        new_active = event.outcome == Outcome.success
        storage.upsert_vpn_health(server, new_active, when)
        transition = _service_transition(prev_active, new_active)
        if transition is None:
            return []  # still up / still down — nothing to alert on
        return [
            _derived_event(
                transition,
                server,
                extra={"prev_active": prev_active, "active": new_active},
                when=when,
            )
        ]

    if event.action == "vpn.status.snapshot":
        current = event.extra.get("clients", []) or []
        previous_row = storage.get_vpn_status(server)
        previous = previous_row["clients"] if previous_row else None
        storage.upsert_vpn_clients(server, current, when)

        derived: list[Event] = []
        derived.extend(detect_concurrent(server, current, when))
        if previous is not None:  # skip diff on first-ever snapshot (baseline)
            derived.extend(diff_sessions(server, previous, current, when))
        return derived

    if event.action == "vpn.cert.snapshot":
        certs = event.extra.get("certs") or []
        storage.upsert_vpn_certs(server, certs, when)
        return []

    return []
