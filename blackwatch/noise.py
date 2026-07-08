"""In-ingest noise control: an in-memory list of mute rules to DROP events
before storage/scoring/notification. Backed by the muted_events table and
refreshed when the UI changes it (and once at startup).

Each mute rule filters on `(action, source_type, username, reason)`:
  * action is always required (event's action must match exactly)
  * source_type, username, reason are optional — NULL matches anything

This lets the operator silence a specific noisy combo without hiding
genuinely bad events on the same action. Example: mute
`rds.auth.failure` where source_type=postgres, username=application_user,
reason=no_pg_hba_entry — silences the "backend pg_hba miss" noise while
still surfacing an actual bad password for application_user."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import storage

if TYPE_CHECKING:  # avoids a cycle at import time
    from .event import Event


@dataclass(frozen=True)
class MuteRule:
    action: str
    source_type: str | None = None
    username: str | None = None
    reason: str | None = None


_muted: list[MuteRule] = []


def refresh() -> None:
    global _muted
    try:
        rows = storage.list_muted_events()
    except Exception:
        return  # DB not ready yet; leave current list in place
    _muted = [
        MuteRule(
            action=r["action"],
            source_type=r["source_type"],
            username=r["username"],
            reason=r["reason"],
        )
        for r in rows
    ]


def _event_field(event: "Event", key: str) -> str | None:
    """Pull one of the mute-filter fields off a normalized Event. `extra`
    is the canonical location (all adapters land username / source_type /
    reason there), but username also falls back to actor.principal for
    events that only set the actor."""
    extra = event.extra or {}
    if key == "source_type":
        return extra.get("source_type") or extra.get("source")
    if key == "username":
        return (
            extra.get("user")
            or extra.get("username")
            or (event.actor.principal if event.actor else None)
        )
    if key == "reason":
        return extra.get("reason")
    return None


def is_muted(event: "Event") -> bool:
    action = event.action
    for rule in _muted:
        if rule.action != action:
            continue
        if rule.source_type is not None and rule.source_type != _event_field(event, "source_type"):
            continue
        if rule.username is not None and rule.username != _event_field(event, "username"):
            continue
        if rule.reason is not None and rule.reason != _event_field(event, "reason"):
            continue
        return True
    return False


def muted_events() -> list[dict[str, str | None]]:
    """UI-friendly view of the current mute rules. Cheap — reads from the
    in-memory list, doesn't hit the DB. Only exposes the four match
    fields (not id / note / created_at) — the API pulls those from
    storage directly."""
    return [
        {
            "action": r.action,
            "source_type": r.source_type,
            "username": r.username,
            "reason": r.reason,
        }
        for r in _muted
    ]
