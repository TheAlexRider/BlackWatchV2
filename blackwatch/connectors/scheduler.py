"""In-process scheduler: a daemon thread that runs enabled+verified connectors
on their configured interval. Deliberately simple — a tick loop, not a cron."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from .. import storage
from ..hosts import staleness as host_staleness
from ..intel import refresher as intel_refresher
from ..rds import staleness as rds_staleness
from ..services import staleness as probe_staleness
from . import operations

_TICK_SECONDS = 10

_thread: threading.Thread | None = None
_stop = threading.Event()


def connector_health_state(connector: dict, *, now: datetime | None = None) -> str:
    """Classify scheduler-facing connector state without conflating failures
    with stale, disabled, unverified, or never-run configurations."""
    now = now or datetime.now(timezone.utc)
    if not connector.get("enabled"):
        return "disabled"
    if not connector.get("verified"):
        return "unverified"
    if connector.get("operation_status") in {"queued", "running"}:
        return "running"
    if connector.get("last_run_at") is None:
        return "never_run"
    if connector.get("last_status") in {"error", "timed_out"}:
        return "failing"
    interval = max(1, int(connector.get("config", {}).get("interval_seconds", 60)))
    age = (now - connector["last_run_at"]).total_seconds()
    return "stale" if age >= max(interval, 60) else "healthy"


def retry_due(connector: dict, *, now: datetime | None = None) -> bool:
    """Whether a stale/failing connector may make its next automatic attempt."""
    now = now or datetime.now(timezone.utc)
    if not (connector.get("enabled") and connector.get("verified")):
        return False
    if connector.get("operation_status") in {"queued", "running"}:
        return False
    next_attempt = connector.get("next_attempt_at")
    if next_attempt is not None and next_attempt > now:
        return False
    if connector.get("last_run_at") is None:
        return False
    interval = max(1, int(connector.get("config", {}).get("interval_seconds", 60)))
    age = (now - connector["last_run_at"]).total_seconds()
    return age >= max(interval, 60)


def _due(connector: dict, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not (connector.get("enabled") and connector.get("verified")):
        return False
    if connector.get("operation_status") in {"queued", "running"}:
        return False
    interval = int(connector.get("config", {}).get("interval_seconds", 60))
    last = connector.get("last_run_at")
    if last is None:
        return True
    next_attempt = connector.get("next_attempt_at")
    if next_attempt is not None and next_attempt > now:
        return False
    age = (now - last).total_seconds()
    # Once a connector is stale, the one-minute backoff stored by the
    # operation manager controls subsequent attempts.
    return age >= max(interval, 60)


def _loop() -> None:
    operations.recover_stale_operations()
    while not _stop.wait(_TICK_SECONDS):
        tick_at = datetime.now(timezone.utc)
        heartbeat_error: str | None = None
        try:
            connectors = storage.list_connectors()
            latest = storage.get_latest_connector_operations([c["id"] for c in connectors])
            for connector in connectors:
                operation = latest.get(connector["id"])
                connector["operation_status"] = operation.get("status") if operation else None
                connector["latest_operation"] = operation
        except Exception as exc:
            heartbeat_error = type(exc).__name__
            try:
                storage.upsert_connector_scheduler_state(
                    heartbeat_at=tick_at, last_tick_at=tick_at,
                    next_tick_at=tick_at, last_error=heartbeat_error,
                )
            except Exception:
                pass
            continue
        for connector in connectors:
            if _due(connector, now=tick_at):
                try:
                    operations.start_connector_operation(
                        connector["id"], kind="scheduled",
                        retry_count=int(connector.get("retry_count") or 0),
                    )
                except Exception:
                    heartbeat_error = "scheduled operation could not be queued"
        try:
            storage.upsert_connector_scheduler_state(
                heartbeat_at=datetime.now(timezone.utc), last_tick_at=tick_at,
                next_tick_at=datetime.now(timezone.utc).replace(microsecond=0),
                last_error=heartbeat_error,
            )
        except Exception:
            pass
        # Absence detection: alert on hosts/probe-agents whose agent went quiet.
        host_staleness.check()
        probe_staleness.check()
        # Long-idle RDS sessions (leaked creds / forgotten psql windows).
        rds_staleness.check()
        # Threat-intel refresh (feeds + MMDBs) once per day; the helper
        # short-circuits when the last successful pass is < 24h old.
        intel_refresher._run_async()


def start() -> None:
    global _thread
    if _thread is not None:
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="connector-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _thread = None
