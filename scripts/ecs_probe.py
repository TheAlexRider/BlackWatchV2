#!/usr/bin/env python3
"""BlackWatch ECS probe agent (SQS + SSM edition).

Runs as ONE Fargate task per VPC. Every INTERVAL seconds:
  1. Refreshes its target list from SSM Parameter Store (cached on disk so a
     transient SSM failure does not blank out the target set).
  2. Runs each check in parallel (asyncio).
  3. Builds an ecs_probe_report and SendMessage's it to a per-VPC SQS queue.
     BlackWatch's aws_ecs_probe_sqs connector polls that queue and feeds the
     report into the ecs.probe adapter (same projection as before).

Auth is IAM — the task role has exactly two permissions, both ARN-scoped:
  * sqs:SendMessage  on the per-VPC queue
  * ssm:GetParameter on the per-VPC targets parameter
Nothing else. No HTTP egress, no bearer tokens, no IP allowlists.

Covers two tiers (the ones that need to be inside the VPC):
  * http_alive  — GET <url>, accept ANY HTTP response (200, 30x, 401, 403, 404).
                  Only timeout / connection refused / 5xx == down. No /health
                  endpoint required — every HTTP server returns SOMETHING on /.
  * tcp         — open TCP socket, close. Up if accepted; down otherwise.

Config (env vars set in the Fargate task definition):
    PROBE_VPC             label this probe reports under            (REQUIRED)
    SQS_QUEUE_URL         per-VPC report queue                      (REQUIRED)
    SSM_PARAM_NAME        SSM param holding the targets JSON list   (REQUIRED)
    AWS_DEFAULT_REGION    queue + param region                      (default us-west-1)
    INTERVAL_SECONDS      tick seconds                              (default 60)
    TARGETS_REFRESH_SEC   re-fetch target list cadence              (default 300)
    DEFAULT_TIMEOUT_SEC   per-check timeout                         (default 5)
    TARGETS_CACHE_PATH    on-disk last-good targets cache           (default /tmp/bw-probe/targets.json)
    AGENT_VERSION         reported in heartbeat                     (default 1.0)
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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

AGENT_VERSION = os.environ.get("AGENT_VERSION", "1.0")
VPC = os.environ.get("PROBE_VPC", "")
QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
SSM_PARAM_NAME = os.environ.get("SSM_PARAM_NAME", "")
REGION = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-west-1"
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "60"))
TARGETS_REFRESH = int(os.environ.get("TARGETS_REFRESH_SEC", "300"))
DEFAULT_TIMEOUT = float(os.environ.get("DEFAULT_TIMEOUT_SEC", "5"))
CACHE_PATH = Path(os.environ.get("TARGETS_CACHE_PATH", "/tmp/bw-probe/targets.json"))

_session = boto3.session.Session(region_name=REGION)
_sqs = _session.client("sqs")
_ssm = _session.client("ssm")

_targets: list[dict[str, Any]] = []
_targets_fetched_at: float = 0.0


# ---------- Target list — SSM with disk cache fallback ---------------------

def _load_cache() -> list[dict[str, Any]] | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return None


def _write_cache(targets: list[dict[str, Any]]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(targets))
    except OSError as exc:
        print(f"targets cache write failed (non-fatal): {exc}", file=sys.stderr)


def _target_id(name: str) -> str:
    """Deterministic UUID per (VPC, service name). Must match the BW connector's
    derivation so the same probe target_id flows end-to-end."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bw-ecs-probe::{VPC}::{name}"))


def fetch_targets() -> None:
    """Pull the targets list from SSM. On failure, keep whatever's in memory
    so a temporary SSM blip never causes a 'no targets' false-recovery storm.
    On cold start, fall back to the on-disk cache if SSM is unavailable."""
    global _targets, _targets_fetched_at
    try:
        resp = _ssm.get_parameter(Name=SSM_PARAM_NAME)
        raw = resp["Parameter"]["Value"]
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            print(f"targets param is not a JSON list (got {type(parsed).__name__})", file=sys.stderr)
            return
        # Re-derive `id` per-target here so the SSM payload can drop it
        # (saves ~45 bytes/target -- meaningful at the 8KB SSM ceiling).
        for t in parsed:
            if isinstance(t, dict) and t.get("name"):
                t["id"] = _target_id(t["name"])
        _targets = parsed
        _targets_fetched_at = time.time()
        _write_cache(parsed)
        print(f"loaded {len(_targets)} targets from {SSM_PARAM_NAME}")
    except (BotoCoreError, ClientError, ValueError) as exc:
        # Don't clobber in-memory targets — keep the last-good list running.
        if not _targets:
            cached = _load_cache()
            if cached is not None:
                _targets = cached
                print(f"ssm fetch failed, loaded {len(cached)} from cache: {exc}",
                      file=sys.stderr)
                return
        print(f"ssm fetch failed (keeping {len(_targets)} in-memory): {exc}",
              file=sys.stderr)


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
                return ("up", r.status, None)
        except urllib.error.HTTPError as e:
            # 401/403/404 = alive and answering; 5xx = degraded.
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
        # Skip targets discovery flagged as un-probeable (no Cloud Map DNS,
        # desiredCount=0, etc.). They still exist in BW's inventory but
        # there's no productive probe to run against them.
        if t.get("enabled") is False:
            continue
        fn = _TIERS.get(t.get("tier"))
        if fn is None:
            continue
        tasks.append(asyncio.create_task(fn(t)))
    if not tasks:
        return []
    return await asyncio.gather(*tasks)


# ---------- Send via SQS ---------------------------------------------------

def build_report(results: list[dict]) -> dict:
    return {
        "kind": "ecs_probe_report",
        "vpc": VPC,
        "agent_version": AGENT_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": results,
    }


def send(payload: dict) -> None:
    try:
        _sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(payload))
        up = sum(1 for r in payload["results"] if r["status"] == "up")
        down = sum(1 for r in payload["results"] if r["status"] == "down")
        deg = sum(1 for r in payload["results"] if r["status"] == "degraded")
        print(f"reported vpc={payload['vpc']} results={len(payload['results'])} "
              f"up={up} down={down} degraded={deg}")
    except (BotoCoreError, ClientError) as exc:
        # No on-disk spool — SQS is the durable buffer once it accepts. If we
        # cannot reach SQS at all, the projection will mark this probe stale
        # within a couple of cycles, which is the signal we want anyway.
        print(f"sqs send failed: {exc}", file=sys.stderr)


def main() -> None:
    missing = [k for k, v in {"PROBE_VPC": VPC, "SQS_QUEUE_URL": QUEUE_URL,
                              "SSM_PARAM_NAME": SSM_PARAM_NAME}.items() if not v]
    if missing:
        print(f"ERROR: required env vars not set: {missing}", file=sys.stderr)
        sys.exit(2)
    print(f"BlackWatch ECS probe v{AGENT_VERSION} vpc={VPC} region={REGION} (every {INTERVAL}s)")
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
