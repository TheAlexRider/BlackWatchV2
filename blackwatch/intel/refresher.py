"""Daily refresh job: pulls MMDBs (if licence key set) and reloads all feeds.

Runs from the connector scheduler; can also be run standalone via
`python -m blackwatch.intel.refresher`."""

from __future__ import annotations

import logging
import threading
import time

from . import db, feeds, geo

log = logging.getLogger(__name__)

_ONE_DAY = 24 * 3600

_state_lock = threading.Lock()
_last_run: float = 0.0
_running = False


def run() -> dict[str, int]:
    global _running, _last_run
    with _state_lock:
        if _running:
            return {}
        _running = True
    try:
        db.init()
        geo.ensure_fresh()
        counts = feeds.refresh_all()
        _last_run = time.time()
        log.info("intel refresh done: %s", counts)
        return counts
    finally:
        with _state_lock:
            _running = False


def maybe_run() -> None:
    """Cheap tick — run if it's been >= 24h since the last successful pass."""
    with _state_lock:
        due = (time.time() - _last_run) >= _ONE_DAY
    if due:
        try:
            run()
        except Exception:
            log.exception("intel refresh failed")


def _run_async() -> None:
    threading.Thread(target=maybe_run, name="intel-refresher", daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    counts = run()
    for feed, n in counts.items():
        print(f"{feed}: {n}")
