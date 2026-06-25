#!/usr/bin/env python3
"""BlackWatch ECS probe agent.

Runs as ONE Fargate task per VPC. Every INTERVAL seconds:
  1. Fetches its target list from BlackWatch (`GET /api/probes/targets`).
  2. Runs each check in parallel (asyncio).
  3. Builds an ecs_probe_report and POSTs to BlackWatch /ingest with the
     same bearer token. The token's mapping (BLACKWATCH_TOKENS in BW) sets
     the module = ecs.probe; the projection handles transitions/hysteresis.

Covers two tiers (the ones that need to be inside the VPC):
  * http_alive  — GET <url>, accept ANY HTTP response (200, 30x, 401, 403, 404).
                  Only timeout / connection refused / 5xx == down. No /health
                  endpoint required — every HTTP server returns SOMETHING on /.
  * tcp         — open TCP socket, close. Up if accepted; down otherwise.

Config (env vars set in the Fargate task definition):
    BLACKWATCH_URL        e.g. https://blackwatch.example.com    (REQUIRED)
    BLACKWATCH_TOKEN      bearer token (per-VPC)                 (REQUIRED)
    INTERVAL_SECONDS      tick seconds                           (default 60)
    TARGETS_REFRESH_SEC   re-fetch target list cadence           (default 300)
    DEFAULT_TIMEOUT_SEC   per-check timeout                      (default 5)
    SPOOL_DIR             local outbound spool                   (default /var/lib/bw-probe)
    AGENT_VERSION         reported in heartbeat                  (default 1.0)
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AGENT_VERSION = os.environ.get("AGENT_VERSION", "1.0")
BW_URL = os.environ.get("BLACKWATCH_URL", "").rstrip("/")
BW_TOKEN = os.environ.get("BLACKWATCH_TOKEN", "")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "60"))
TARGETS_REFRESH = int(os.environ.get("TARGETS_REFRESH_SEC", "300"))
DEFAULT_TIMEOUT = float(os.environ.get("DEFAULT_TIMEOUT_SEC", "5"))
SPOOL_DIR = Path(os.environ.get("SPOOL_DIR", "/var/lib/bw-probe")) / "spool"

_targets: list[dict] = []
_targets_fetched_at: float = 0.0
_vpc: str = "unknown"


def _http(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Tiny stdlib HTTP client. Avoids pulling httpx into the container; this is
    the only HTTP we do outbound, so a 40-line urllib helper is enough."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BW_URL}{path}", method=method, data=data,
        headers={
            "Content-Type": "application/json",
            "X-BlackWatch-Token": BW_TOKEN,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode() or "{}"
        return r.status, json.loads(raw)


def fetch_targets() -> None:
    global _targets, _targets_fetched_at, _vpc
    try:
        _, body = _http("GET", "/api/probes/targets")
    except Exception as exc:
        print(f"target fetch failed: {exc}", file=sys.stderr)
        return
    _targets = body.get("targets") or []
    _vpc = body.get("vpc") or "unknown"
    _targets_fetched_at = time.time()
    print(f"loaded {len(_targets)} targets for vpc={_vpc}")


# ---------- Checks (async — 50 in parallel takes ~5s) ----------------------

async def check_http_alive(target: dict) -> dict:
    cfg = target.get("config") or {}
    url = cfg.get("url")
    timeout = float(cfg.get("timeout_seconds") or DEFAULT_TIMEOUT)
    if not url:
        return _result(target, "unknown", error="missing url")
    loop = asyncio.get_event_loop()
    started = time.perf_counter()
    def _do():
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                # Any HTTP response is success. Only network failure = down.
                return ("up", r.status, None)
        except urllib.error.HTTPError as e:
            # 401/403/404 are "process is alive and answered" — up.
            # 5xx is "process answered but service-side error" — degraded.
            if 500 <= e.code < 600:
                return ("degraded", e.code, f"HTTP {e.code}")
            return ("up", e.code, None)
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as e:
            return ("down", None, str(e)[:120])
        except Exception as e:
            return ("down", None, str(e)[:120])
    status, code, err = await loop.run_in_executor(None, _do)
    return _result(target, status, latency_ms=int((time.perf_counter() - started) * 1000),
                   error=err, extra={"http_status": code})


async def check_tcp(target: dict) -> dict:
    cfg = target.get("config") or {}
    host = cfg.get("host")
    port = int(cfg.get("port") or 0)
    timeout = float(cfg.get("timeout_seconds") or DEFAULT_TIMEOUT)
    if not host or not port:
        return _result(target, "unknown", error="missing host/port")
    loop = asyncio.get_event_loop()
    started = time.perf_counter()
    def _do():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return ("up", None)
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            return ("down", str(e)[:120])
        finally:
            try:
                s.close()
            except Exception:
                pass
    status, err = await loop.run_in_executor(None, _do)
    return _result(target, status, latency_ms=int((time.perf_counter() - started) * 1000),
                   error=err, extra={"host": host, "port": port})


def _result(target: dict, status: str, *, latency_ms: int | None = None,
            error: str | None = None, extra: dict | None = None) -> dict:
    return {
        "target_id": target["id"],
        "name": target.get("name"),
        "tier": target.get("tier"),
        "status": status,
        "latency_ms": latency_ms,
        "error": error,
        "extra": extra or {},
    }


_TIERS = {"http_alive": check_http_alive, "tcp": check_tcp}


async def run_all_checks() -> list[dict]:
    tasks = []
    for t in _targets:
        fn = _TIERS.get(t.get("tier"))
        if fn is None:
            continue
        tasks.append(asyncio.create_task(fn(t)))
    if not tasks:
        return []
    return await asyncio.gather(*tasks)


# ---------- Send + spool ----------------------------------------------------

def build_report(results: list[dict]) -> dict:
    return {
        "kind": "ecs_probe_report",
        "vpc": _vpc,
        "agent_version": AGENT_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": results,
    }


def _spool(payload: dict) -> None:
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    (SPOOL_DIR / f"{int(time.time() * 1000)}.json").write_text(json.dumps(payload))


def _flush_spool() -> None:
    if not SPOOL_DIR.exists():
        return
    for f in sorted(SPOOL_DIR.glob("*.json")):
        try:
            _http("POST", "/ingest", body=json.loads(f.read_text()))
            f.unlink()
        except Exception:
            return


def send(payload: dict) -> None:
    try:
        _flush_spool()
        _http("POST", "/ingest", body=payload)
        up = sum(1 for r in payload["results"] if r["status"] == "up")
        down = sum(1 for r in payload["results"] if r["status"] == "down")
        deg = sum(1 for r in payload["results"] if r["status"] == "degraded")
        print(f"reported vpc={payload['vpc']} results={len(payload['results'])} "
              f"up={up} down={down} degraded={deg}")
    except Exception as exc:
        print(f"send failed, spooling: {exc}", file=sys.stderr)
        _spool(payload)


def main() -> None:
    if not BW_URL or not BW_TOKEN:
        print("ERROR: set BLACKWATCH_URL and BLACKWATCH_TOKEN", file=sys.stderr)
        sys.exit(2)
    print(f"BlackWatch ECS probe v{AGENT_VERSION} -> {BW_URL} (every {INTERVAL}s)")
    once = "--once" in sys.argv
    while True:
        if time.time() - _targets_fetched_at > TARGETS_REFRESH:
            fetch_targets()
        results = asyncio.run(run_all_checks())
        send(build_report(results))
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
