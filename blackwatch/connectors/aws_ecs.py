"""AWS-side ECS health-status reader.

Runs on BlackWatch's in-process scheduler (no VPC presence needed — these are
control-plane API calls). For each probe_target in the configured VPC whose
tier is ecs_health or ecs_running, ask AWS what it knows:

  * tier `ecs_health` — read `containers[].healthStatus` from describe_tasks.
      AWS aggregates the container-level healthCheck (defined in the task def)
      and tells us HEALTHY / UNHEALTHY / UNKNOWN per container. We aggregate
      across the service's tasks: any UNHEALTHY -> down, all HEALTHY -> up,
      all UNKNOWN -> 'unknown' (we don't pretend to have an opinion).
  * tier `ecs_running` — for workers/services WITHOUT a health check defined.
      Use `runningCount` smoothed over `running_smoothing_minutes` so a brief
      Fargate Spot interruption doesn't page anyone. We track a small per-target
      in-memory window of (timestamp, was_below_desired) and only declare down
      when the window has been continuously below for the configured minutes.

Builds the same `ecs_probe_report` shape the in-VPC probe agent produces and
feeds it into the existing `ecs.probe` adapter, so the projection / rules /
notifications pipeline is untouched."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .. import pipeline, storage
from .models import AwsEcsHealthConfig


# Per-target sliding-window state for tier=ecs_running. Keyed by target_id.
# Each value is a list of (epoch_seconds, below_desired_bool). We trim entries
# older than the smoothing window on each tick.
_running_windows: dict[str, list[tuple[float, bool]]] = defaultdict(list)


def _client(cfg: AwsEcsHealthConfig):
    import boto3
    session = boto3.session.Session(
        profile_name=cfg.aws_profile or None, region_name=cfg.aws_region
    )
    return session.client("ecs")


def _aggregate_health(tasks: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Across all tasks in a service, decide an overall status from container
    healthStatus values. Returns (status, extra)."""
    total = len(tasks)
    healthy = unhealthy = unknown = 0
    for t in tasks:
        # Take the worst status across the task's containers (single bad
        # container = task is in trouble).
        statuses = [c.get("healthStatus") for c in t.get("containers") or []]
        if not statuses:
            unknown += 1
            continue
        if "UNHEALTHY" in statuses:
            unhealthy += 1
        elif all(s == "HEALTHY" for s in statuses if s):
            healthy += 1
        else:
            unknown += 1
    extra = {"total_tasks": total, "healthy": healthy,
             "unhealthy": unhealthy, "unknown": unknown}
    if total == 0:
        return "down", extra              # service has no tasks at all
    if unhealthy > 0:
        return ("degraded" if healthy > 0 else "down"), extra
    if healthy == total:
        return "up", extra
    # Everything UNKNOWN — AWS has no healthCheck configured. Don't lie.
    return "unknown", extra


def _running_status(
    target_id: str, running: int, desired: int, now: float, smoothing_seconds: int,
) -> tuple[str, dict[str, Any]]:
    """Smoothed runningCount check for workers / services with no healthCheck.
    Records below-desired moments in a sliding window; only declares down once
    the whole window has been below."""
    below = running < desired
    window = _running_windows[target_id]
    window.append((now, below))
    cutoff = now - smoothing_seconds
    _running_windows[target_id] = [(t, b) for (t, b) in window if t >= cutoff]
    window = _running_windows[target_id]
    extra = {"running": running, "desired": desired,
             "below_window_pct": round(
                 100 * sum(1 for _, b in window if b) / max(1, len(window)), 1)}

    if not below:
        return "up", extra
    span = window[-1][0] - window[0][0] if window else 0
    if span >= smoothing_seconds and all(b for _, b in window):
        return "down", extra
    return "degraded", extra


def poll(cfg: AwsEcsHealthConfig) -> dict[str, Any]:
    """One scheduled tick. Builds an ecs_probe_report and feeds it through the
    standard ingest pipeline. The adapter -> projection -> rules path is
    identical to what the in-VPC probe agent triggers."""
    ecs = _client(cfg)
    targets = [t for t in storage.list_probe_targets(vpc=cfg.vpc, enabled_only=True)
               if t["tier"] in ("ecs_health", "ecs_running")]
    smoothing_seconds = max(60, cfg.running_smoothing_minutes * 60)
    now_epoch = time.time()
    results: list[dict[str, Any]] = []

    # Group by cluster to batch API calls.
    by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in targets:
        cluster = (t.get("config") or {}).get("cluster")
        if cluster:
            by_cluster[cluster].append(t)

    for cluster, ts in by_cluster.items():
        for tgt in ts:
            cfg_d = tgt["config"] or {}
            service = cfg_d.get("service")
            if not service:
                continue
            try:
                # 1. List tasks for the service.
                arns = ecs.list_tasks(
                    cluster=cluster, serviceName=service, desiredStatus="RUNNING",
                ).get("taskArns", [])
                tasks = []
                if arns:
                    tasks = ecs.describe_tasks(cluster=cluster, tasks=arns).get("tasks", [])
                # 2. Describe the service for runningCount / desiredCount.
                svc_desc = ecs.describe_services(
                    cluster=cluster, services=[service]
                ).get("services", [])
                svc = svc_desc[0] if svc_desc else {}
                running = svc.get("runningCount", 0)
                desired = svc.get("desiredCount", 0)

                if tgt["tier"] == "ecs_health":
                    status, extra = _aggregate_health(tasks)
                else:  # ecs_running
                    status, extra = _running_status(
                        tgt["id"], running, desired, now_epoch, smoothing_seconds,
                    )
                extra["cluster"] = cluster
                extra["service"] = service
                results.append({
                    "target_id": tgt["id"], "name": tgt["name"], "tier": tgt["tier"],
                    "status": status, "latency_ms": None, "error": None, "extra": extra,
                })
            except Exception as exc:
                results.append({
                    "target_id": tgt["id"], "name": tgt["name"], "tier": tgt["tier"],
                    "status": "unknown", "latency_ms": None,
                    "error": str(exc)[:200], "extra": {"cluster": cluster, "service": service},
                })

    payload = {
        "kind": "ecs_probe_report",
        "vpc": cfg.vpc,
        "agent_version": "bw-aws-reader-1.0",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": results,
    }
    stats = pipeline.ingest_payload(
        "ecs.probe", payload, transport="poll",
    )
    return {"ingested": stats.get("ingested", 0), "results": len(results)}
