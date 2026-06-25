"""ECS probe adapter.

Consumes reports from two sources, both shaped the same way:
  1. The in-VPC probe agent (`scripts/ecs_probe.py`) — handles `http_alive` and
     `tcp` tier targets (needs network presence in the VPC).
  2. The BlackWatch-side AWS reader (`connectors/aws_ecs.py`) — handles
     `ecs_health` and `ecs_running` tiers (pure AWS API calls, no VPC needed).

Both produce a report of this shape:

    {
      "kind": "ecs_probe_report",
      "vpc": "prod" | "dev" | ...,
      "agent_version": "1.0",
      "observed_at": "2026-06-03T12:00:00Z",
      "results": [
        {
          "target_id": "<uuid>",
          "name": "ai-gateway-api",
          "tier": "ecs_health" | "ecs_running" | "http_alive" | "tcp",
          "status": "up" | "down" | "degraded" | "unknown",
          "latency_ms": 42,
          "error": null | "...",
          "extra": {...}
        },
        ...
      ]
    }

We emit:
  * probe.agent.heartbeat       — projection-only, updates probe_agent_status
  * service.probe.result        — projection-only, drives transition events

The pipeline's projection-only set (see pipeline.py) routes both straight to the
projection; the projection's job is to compare each result vs. the stored status
and emit `service.up` / `service.down` / `service.degraded` transitions with
hysteresis. Pure-data adapter — no DB, no state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..event import Category, Event, Outcome, Source, Target, Transport
from .base import Adapter, IngestContext


class EcsProbeAdapter(Adapter):
    module = "ecs.probe"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict) or raw.get("kind") != "ecs_probe_report":
            return []
        vpc = raw.get("vpc") or "unknown"
        agent_version = raw.get("agent_version")
        observed_at = _parse_iso(raw.get("observed_at")) or datetime.now(timezone.utc)
        try:
            transport = Transport(ctx.transport)
        except ValueError:
            transport = Transport.api
        results = raw.get("results") or []

        def src() -> Source:
            return Source(module=self.module, transport=transport)

        events: list[Event] = [
            Event(
                source=src(),
                event_time=observed_at,
                category=Category.other,
                action="probe.agent.heartbeat",
                outcome=Outcome.success,
                target=Target(id=vpc, type="probe.agent", name=f"probe-{vpc}"),
                extra={
                    "vpc": vpc,
                    "agent_version": agent_version,
                    "result_count": len(results),
                },
                raw={"kind": "ecs_probe_report", "vpc": vpc},
            )
        ]

        for r in results:
            if not isinstance(r, dict):
                continue
            target_id = r.get("target_id")
            if not target_id:
                continue
            events.append(
                Event(
                    source=src(),
                    event_time=observed_at,
                    category=Category.other,
                    action="service.probe.result",
                    outcome=(Outcome.success if r.get("status") == "up" else Outcome.failure),
                    target=Target(id=target_id, type="ecs.service", name=r.get("name")),
                    extra={
                        "vpc": vpc,
                        "target_id": target_id,
                        "name": r.get("name"),
                        "tier": r.get("tier"),
                        "status": r.get("status") or "unknown",
                        "latency_ms": r.get("latency_ms"),
                        "error": r.get("error"),
                        "result_extra": r.get("extra") or {},
                    },
                    raw=r,
                )
            )
        return events


def _parse_iso(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
