"""Stateful correlation (Phase D foothold).

Two parallel sliding-window brute-force detectors, fed by the same auth events:

  * Per-IP — catches an attacker hammering one box from one source:
        host.auth.ssh.failure -> host.bruteforce
        vpn.auth.failure      -> vpn.bruteforce
  * Per-user — catches credential stuffing where the same identity is attacked
    from many different IPs (per-IP detector would never trip):
        host.auth.ssh.failure -> host.bruteforce.user
        vpn.auth.failure      -> vpn.bruteforce.user

Both can fire on the same event if both criteria are met — they're separate
signals and downstream rules/channels can de-dupe if desired. THRESHOLD failures
within WINDOW seconds on the same key emit ONE event; the same key is then
suppressed for the rest of the window.

Thread-safety: counters are shared mutable state accessed from FastAPI sync
handlers (threadpool). All access guarded by a single Lock.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from .event import (
    Actor,
    Category,
    Event,
    Outcome,
    Source,
    Target,
    Transport,
)

# Threshold + window — kept conservative; tweak via config later if needed.
THRESHOLD = 5
WINDOW_SECONDS = 300

# action -> (derived_action, source.module, category)
_WATCH_IP: dict[str, tuple[str, str, Category]] = {
    "host.auth.ssh.failure": ("host.bruteforce", "ec2.host", Category.host),
    "vpn.auth.failure": ("vpn.bruteforce", "vpn.openvpn", Category.vpn),
}
_WATCH_USER: dict[str, tuple[str, str, Category]] = {
    "host.auth.ssh.failure": ("host.bruteforce.user", "ec2.host", Category.host),
    "vpn.auth.failure": ("vpn.bruteforce.user", "vpn.openvpn", Category.vpn),
}

_lock = threading.Lock()
# Each counter dimension has its own attempt deques + alert-suppression map.
# Keyed by (action, dimension_value) where dimension_value is the IP or the
# principal — keeping them in separate dicts means per-IP suppression and
# per-user suppression never collide.
_ip_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_ip_alerted: dict[tuple[str, str], float] = {}
_user_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_user_alerted: dict[tuple[str, str], float] = {}


def _now() -> float:
    """Indirection so tests can monkeypatch a fake clock."""
    return time.time()


def _check_dimension(
    event: Event,
    dim_value: str,
    dim_label: str,
    attempts: dict[tuple[str, str], deque[float]],
    alerted: dict[tuple[str, str], float],
    watch_map: dict[str, tuple[str, str, Category]],
) -> list[Event]:
    """Run one sliding-window check on a single dimension (IP or user).
    Returns 0 or 1 derived events. Acquires/releases the shared lock for the
    counter mutation; event construction happens outside the lock."""
    if event.action not in watch_map:
        return []
    now = _now()
    key = (event.action, dim_value)

    with _lock:
        bucket = attempts[key]
        while bucket and now - bucket[0] > WINDOW_SECONDS:
            bucket.popleft()
        bucket.append(now)
        if len(bucket) < THRESHOLD:
            return []
        last_alert = alerted.get(key, 0.0)
        if last_alert and now - last_alert < WINDOW_SECONDS:
            return []  # already alerted in this window — suppress
        alerted[key] = now
        count = len(bucket)

    derived_action, module, category = watch_map[event.action]
    extra: dict[str, Any] = {
        "count_in_window": count,
        "window_seconds": WINDOW_SECONDS,
        "threshold": THRESHOLD,
        "trigger_event_id": event.event_id,
        # Always include both dims for downstream context, populated where known.
        "source_ip": event.actor.source_ip,
        "principal": event.actor.principal,
        "dimension": dim_label,           # which counter fired ("source_ip" / "principal")
    }
    return [
        Event(
            source=Source(module=module, vendor=event.source.vendor,
                          account=event.source.account, region=event.source.region,
                          transport=Transport.poll),
            event_time=datetime.now(timezone.utc),
            category=category,
            action=derived_action,
            outcome=Outcome.failure,
            actor=Actor(principal=event.actor.principal, source_ip=event.actor.source_ip),
            target=Target(
                id=event.target.id if event.target else None,
                type=event.target.type if event.target else None,
                name=event.target.name if event.target else None,
            ),
            extra=extra,
            raw={"derived": "bruteforce", "trigger_action": event.action,
                 "dimension": dim_label},
        )
    ]


def observe(event: Event) -> list[Event]:
    """Run both detectors against this event; return all derived events.

    A single trigger event can produce up to two derived events (per-IP AND
    per-user), if both thresholds are crossed by it. That's intentional — they
    convey different signals."""
    results: list[Event] = []
    if event.actor.source_ip:
        results.extend(_check_dimension(
            event, event.actor.source_ip, "source_ip",
            _ip_attempts, _ip_alerted, _WATCH_IP,
        ))
    if event.actor.principal:
        results.extend(_check_dimension(
            event, event.actor.principal, "principal",
            _user_attempts, _user_alerted, _WATCH_USER,
        ))
    return results


def reset_state() -> None:
    """Tests can clear in-memory state between runs."""
    with _lock:
        _ip_attempts.clear()
        _ip_alerted.clear()
        _user_attempts.clear()
        _user_alerted.clear()
