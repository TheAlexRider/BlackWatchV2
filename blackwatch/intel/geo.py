"""GeoIP + ASN lookup via MaxMind GeoLite2 MMDB files.

Requires MAXMIND_LICENSE_KEY. If unset (or maxminddb not installed), lookups
return empty and we log ONCE — the enrichment path stays alive."""

from __future__ import annotations

import gzip
import io
import logging
import os
import tarfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from .db import data_dir

log = logging.getLogger(__name__)

_STALE_SECS = 7 * 24 * 3600
_TIMEOUT = 60

_EDITIONS = {
    "country": "GeoLite2-Country",
    "asn":     "GeoLite2-ASN",
}

_readers: dict[str, Any] = {}
_lock = threading.Lock()
_missing_key_logged = False


def _mmdb_path(edition: str) -> Path:
    return data_dir() / f"{_EDITIONS[edition]}.mmdb"


def _download(edition: str, license_key: str) -> bool:
    edition_id = _EDITIONS[edition]
    url = (
        f"https://download.maxmind.com/app/geoip_download?edition_id={edition_id}"
        f"&license_key={license_key}&suffix=tar.gz"
    )
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:  # noqa: S310
            data = resp.read()
    except Exception as exc:
        log.warning("mmdb download failed for %s: %s", edition_id, exc)
        return False
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.name.endswith(".mmdb")), None)
            if member is None:
                log.warning("mmdb tar had no .mmdb member for %s", edition_id)
                return False
            f = tar.extractfile(member)
            if f is None:
                return False
            _mmdb_path(edition).write_bytes(f.read())
    except (tarfile.TarError, gzip.BadGzipFile, OSError) as exc:
        log.warning("mmdb extract failed for %s: %s", edition_id, exc)
        return False
    return True


def ensure_fresh() -> None:
    key = os.environ.get("MAXMIND_LICENSE_KEY")
    global _missing_key_logged
    if not key:
        if not _missing_key_logged:
            log.info("MAXMIND_LICENSE_KEY unset; GeoIP disabled")
            _missing_key_logged = True
        return
    for edition in _EDITIONS:
        p = _mmdb_path(edition)
        stale = (not p.exists()) or (time.time() - p.stat().st_mtime > _STALE_SECS)
        if stale:
            _download(edition, key)


def _reader(edition: str):
    try:
        import maxminddb  # type: ignore
    except ImportError:
        return None
    with _lock:
        r = _readers.get(edition)
        p = _mmdb_path(edition)
        if not p.exists():
            return None
        if r is None:
            _readers[edition] = maxminddb.open_database(str(p))
        return _readers[edition]


def lookup(ip: str) -> dict[str, Any]:
    """Return {country, asn, asn_org} — any of which may be missing."""
    out: dict[str, Any] = {}
    r_country = _reader("country")
    if r_country is not None:
        try:
            rec = r_country.get(ip)
            if rec and isinstance(rec, dict):
                country = rec.get("country") or rec.get("registered_country") or {}
                iso = country.get("iso_code") if isinstance(country, dict) else None
                if iso:
                    out["country"] = iso
        except (ValueError, KeyError):
            pass
    r_asn = _reader("asn")
    if r_asn is not None:
        try:
            rec = r_asn.get(ip)
            if rec and isinstance(rec, dict):
                if rec.get("autonomous_system_number"):
                    out["asn"] = int(rec["autonomous_system_number"])
                if rec.get("autonomous_system_organization"):
                    out["asn_org"] = str(rec["autonomous_system_organization"])
        except (ValueError, KeyError):
            pass
    return out
