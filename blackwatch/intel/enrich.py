"""Hot-path enrichment: mutate event.extra['intel'] with country/ASN/feed tags.

Never raises: the pipeline hook wraps this in try/except but we also swallow
per-IP failures internally so one malformed observable can't blank the whole
enrichment block."""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from typing import Any

from ..event import Event, ObservableType
from . import db, geo

log = logging.getLogger(__name__)

# Bogon ranges (RFC1918, loopback, link-local, CGNAT, multicast, reserved).
# Cheap check with ipaddress flags — no lookup needed.

_CACHE_TTL = 300
_CACHE_MAX = 4096
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(ip: str) -> dict[str, Any] | None:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(ip)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    return None


def _store(ip: str, value: dict[str, Any]) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[ip] = (time.time(), value)


def _classify(ip_str: str) -> dict[str, Any] | None:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return None
    if addr.version != 4:
        # v6 support is possible later; for now only classify bogon-ness.
        return {
            "feeds": [],
            "is_tor": False,
            "is_bogon": addr.is_private or addr.is_loopback
            or addr.is_link_local or addr.is_multicast or addr.is_reserved
            or addr.is_unspecified,
        }
    is_bogon = (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )
    out: dict[str, Any] = {"feeds": [], "is_tor": False, "is_bogon": is_bogon}
    if not is_bogon:
        try:
            matches = db.lookup_ip4(int(addr))
        except Exception as exc:
            log.debug("intel lookup failed for %s: %s", ip_str, exc)
            matches = []
        feed_set: list[str] = []
        for feed, _tags in matches:
            if feed not in feed_set:
                feed_set.append(feed)
            if feed == "tor_exit":
                out["is_tor"] = True
        out["feeds"] = feed_set
        geo_data = geo.lookup(ip_str)
        out.update(geo_data)
    return out


def _lookup(ip_str: str) -> dict[str, Any] | None:
    hit = _cached(ip_str)
    if hit is not None:
        return hit
    val = _classify(ip_str)
    if val is not None:
        _store(ip_str, val)
    return val


def enrich_event(event: Event) -> None:
    """Add {'intel': {...}} to event.extra for the first useful IP observable.

    We keep one block per event (not per observable) — the schema is simple
    and the UI shows one badge. If multiple IPs appear, non-bogon public IPs
    win over bogons."""
    ips = [o.value for o in event.observables if o.type == ObservableType.ip and o.value]
    # actor source_ip is often the interesting one and may not be duplicated
    src = getattr(event.actor, "source_ip", None)
    if src and src not in ips:
        ips.append(src)
    if not ips:
        return
    picked: dict[str, Any] | None = None
    for ip in ips:
        info = _lookup(ip)
        if info is None:
            continue
        if picked is None:
            picked = info
        if not info.get("is_bogon"):
            picked = info
            break
    if picked is None:
        return
    event.extra.setdefault("intel", picked)
