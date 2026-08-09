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
from .runner import run_connector

_TICK_SECONDS = 10

_thread: threading.Thread | None = None
_stop = threading.Event()


def _due(connector: dict) -> bool:
    if not (connector.get("enabled") and connector.get("verified")):
        return False
    interval = int(connector.get("config", {}).get("interval_seconds", 60))
    last = connector.get("last_run_at")
    if last is None:
        return True
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return age >= interval


def _loop() -> None:
    while not _stop.wait(_TICK_SECONDS):
        try:
            connectors = storage.list_connectors()
        except Exception:
            continue
        for connector in connectors:
            if _due(connector):
                try:
                    run_connector(connector["id"])
                except Exception:
                    pass  # status is recorded inside run_connector
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
