"""In-process scheduler: a daemon thread that runs enabled+verified connectors
on their configured interval. Deliberately simple — a tick loop, not a cron."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

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
    if (
        connector.get("last_status") in {"error", "timed_out"}
        or connector.get("scheduler_reason") in {"timeout", "process_restart"}
    ):
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
    if (
        next_attempt is not None
        and (
            connector.get("last_status") in {"error", "timed_out"}
            or connector.get("scheduler_reason") in {"timeout", "process_restart"}
        )
    ):
        return True
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
    next_attempt = connector.get("next_attempt_at")
    if next_attempt is not None and next_attempt > now:
        return False
    if (
        next_attempt is not None
        and (
            connector.get("last_status") in {"error", "timed_out"}
            or connector.get("scheduler_reason") in {"timeout", "process_restart"}
        )
    ):
        return True
    if last is None:
        return True
    age = (now - last).total_seconds()
    # Once a connector is stale, the one-minute backoff stored by the
    # operation manager controls subsequent attempts.
    return age >= max(interval, 60)


def _reconcile_retry_metadata(
    connector: dict, operation: dict | None,
) -> None:
    """Repair scheduler metadata if a terminal operation committed first.

    Operation history is authoritative. This makes a partial failure between
    the operation write and connector metadata write self-healing on the next
    scheduler tick without touching evidence or connector configuration.
    """
    if not operation:
        return
    status = operation.get("status")
    if status == "succeeded":
        desired = {
            "retry_count": 0,
            "next_attempt_at": None,
            "scheduler_reason": None,
        }
    elif status in {"failed", "timed_out"} and operation.get("next_attempt_at") is not None:
        outcome = operation.get("outcome") or {}
        reason = "process_restart" if outcome.get("reason") == "process_restart" else (
            operation.get("error_category") or "unknown"
        )
        desired = {
            "retry_count": int(operation.get("retry_count") or 0),
            "next_attempt_at": operation.get("next_attempt_at"),
            "scheduler_reason": reason,
        }
    else:
        return
    if all(connector.get(key) == value for key, value in desired.items()):
        return
    storage.set_connector_retry(
        connector["id"], retry_count=desired["retry_count"],
        next_attempt_at=desired["next_attempt_at"], reason=desired["scheduler_reason"],
    )
    connector.update(desired)


def _loop() -> None:
    try:
        operations.reap_stale_operations()
    except Exception:
        # The first recovery pass must not permanently kill the scheduler if
        # Postgres is still becoming ready during application startup.
        pass
    while not _stop.wait(_TICK_SECONDS):
        tick_at = datetime.now(timezone.utc)
        heartbeat_error: str | None = None
        try:
            operations.reap_stale_operations()
        except Exception as exc:
            heartbeat_error = f"stale-operation recovery: {type(exc).__name__}"
        try:
            connectors = storage.list_connectors()
            latest = storage.get_latest_connector_operations([c["id"] for c in connectors])
            for connector in connectors:
                operation = latest.get(connector["id"])
                connector["operation_status"] = operation.get("status") if operation else None
                connector["latest_operation"] = operation
                _reconcile_retry_metadata(connector, operation)
        except Exception as exc:
            heartbeat_error = type(exc).__name__
            try:
                storage.upsert_connector_scheduler_state(
                    heartbeat_at=tick_at, last_tick_at=tick_at,
                    next_tick_at=tick_at + timedelta(seconds=_TICK_SECONDS),
                    last_error=heartbeat_error,
                )
            except Exception:
                pass
            continue
        for connector in connectors:
            if _due(connector, now=tick_at):
                try:
                    result = operations.start_connector_operation(
                        connector["id"], kind="scheduled",
                        retry_count=int(connector.get("retry_count") or 0),
                    )
                    if result.get("reason") == "concurrency_limit":
                        heartbeat_error = "concurrency_limit"
                except Exception:
                    heartbeat_error = "scheduled operation could not be queued"
        # Absence detection: alert on hosts/probe-agents whose agent went quiet.
        for name, check in (
            ("host staleness", host_staleness.check),
            ("probe staleness", probe_staleness.check),
            ("RDS staleness", rds_staleness.check),
        ):
            try:
                check()
            except Exception as exc:
                heartbeat_error = heartbeat_error or f"{name}: {type(exc).__name__}"
        # Threat-intel refresh (feeds + MMDBs) once per day; the helper
        # short-circuits when the last successful pass is < 24h old.
        try:
            intel_refresher._run_async()
        except Exception as exc:
            heartbeat_error = heartbeat_error or f"threat-intel refresh: {type(exc).__name__}"
        try:
            storage.upsert_connector_scheduler_state(
                heartbeat_at=datetime.now(timezone.utc), last_tick_at=tick_at,
                next_tick_at=tick_at + timedelta(seconds=_TICK_SECONDS),
                last_error=heartbeat_error,
            )
        except Exception:
            pass


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
