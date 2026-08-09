"""Pull free/OSS threat-intel feeds and load them into intel.db.

All feeds share the same shape: a plain-text list of CIDRs (or single IPs)
with per-file comment conventions. We normalise each to int ranges so the
hot lookup is a single indexed BETWEEN query."""

from __future__ import annotations

import ipaddress
import logging
import urllib.error
import urllib.request
from typing import Iterable

from . import db

log = logging.getLogger(__name__)

FEEDS: dict[str, tuple[str, str]] = {
    # feed_name: (url, default_tags)
    "spamhaus_drop":  ("https://www.spamhaus.org/drop/drop.txt",         "spamhaus,drop"),
    "spamhaus_edrop": ("https://www.spamhaus.org/drop/edrop.txt",        "spamhaus,edrop"),
    "firehol_level1": ("https://iplists.firehol.org/files/firehol_level1.netset", "firehol,level1"),
    "tor_exit":       ("https://check.torproject.org/torbulkexitlist",   "tor,exit"),
}

_UA = "BlackWatch-Intel/1.0 (+https://github.com/BlackWatchV2)"
_TIMEOUT = 30


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted urls)
        return resp.read().decode("utf-8", errors="replace")


def _cidr_to_range(cidr: str) -> tuple[int, int] | None:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    if net.version != 4:
        return None
    return int(net.network_address), int(net.broadcast_address)


def _parse_lines(text: str) -> Iterable[str]:
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        # spamhaus lines: "1.2.3.0/24 ; SBL12345"
        token = s.split()[0].split(";")[0].strip()
        if token:
            yield token


def refresh_feed(name: str) -> int:
    url, tags = FEEDS[name]
    try:
        text = _fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("intel feed %s fetch failed: %s", name, exc)
        db.record_failure(name, url, f"fetch_error:{exc}")
        return 0

    rows: list[tuple[int, int, str]] = []
    for token in _parse_lines(text):
        rng = _cidr_to_range(token if "/" in token else token + "/32")
        if rng:
            rows.append((rng[0], rng[1], tags))
    if not rows:
        db.record_failure(name, url, "empty_parse")
        return 0
    return db.replace_feed(name, url, rows)


def refresh_all() -> dict[str, int]:
    out: dict[str, int] = {}
    for name in FEEDS:
        try:
            out[name] = refresh_feed(name)
        except Exception as exc:
            log.exception("intel feed %s crashed: %s", name, exc)
            out[name] = 0
    return out
