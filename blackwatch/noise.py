"""In-ingest noise control: a small in-memory set of event actions to DROP
before they're stored/scored/notified. Backed by the muted_actions table and
refreshed when the UI changes it (and once at startup)."""

from __future__ import annotations

from . import storage

_muted: set[str] = set()


def refresh() -> None:
    global _muted
    try:
        _muted = set(storage.list_muted_actions())
    except Exception:
        pass  # DB not ready yet; leave current set


def is_muted(action: str) -> bool:
    return action in _muted


def muted_actions() -> list[str]:
    return sorted(_muted)
