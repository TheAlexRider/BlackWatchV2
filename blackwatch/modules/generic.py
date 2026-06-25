"""Generic passthrough adapter — the universal webhook intake.

It maps any JSON payload onto the normalized envelope on a best-effort basis,
honoring envelope-shaped fields if present and always preserving the original
payload in `raw`. This is the Phase 0 workhorse and the permanent fallback for
any source that does not yet have a dedicated module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor,
    Event,
    Observable,
    Source,
    Transport,
)
from .base import Adapter, IngestContext


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_transport(value: str) -> Transport:
    try:
        return Transport(value)
    except ValueError:
        return Transport.webhook


class GenericAdapter(Adapter):
    module = "generic"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        body: dict[str, Any] = raw if isinstance(raw, dict) else {"value": raw}

        source = Source(
            module=ctx.module,
            vendor=body.get("vendor"),
            account=ctx.account,
            region=ctx.region,
            transport=_as_transport(ctx.transport),
        )

        actor = Actor(**body["actor"]) if isinstance(body.get("actor"), dict) else Actor()
        target_data = body.get("target") if isinstance(body.get("target"), dict) else {}

        observables: list[Observable] = []
        for obs in body.get("observables", []) or []:
            if isinstance(obs, dict) and "type" in obs and "value" in obs:
                observables.append(Observable(type=obs["type"], value=str(obs["value"])))

        event = Event(
            source=source,
            event_time=_parse_time(body.get("event_time")) or datetime.now(timezone.utc),
            category=body.get("category", "other"),
            action=body.get("action", "generic.event"),
            outcome=body.get("outcome", "unknown"),
            actor=actor,
            target=target_data,
            observables=observables,
            tags=list(body.get("tags", []) or []),
            extra=body.get("extra", {}) if isinstance(body.get("extra"), dict) else {},
            raw=raw,
        )
        return [event]
