"""Durable DB-backed investigation scan worker."""
from __future__ import annotations
import threading
import time
from . import storage

class Worker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="investigation-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread: self._thread.join(timeout=2)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = None
            try:
                job = storage.claim_investigation_scan()
                if job:
                    row = storage.get_investigation(job["investigation_id"])
                    observable = next((v.split(":", 1)[1] for v in row["observables"] if v.startswith("ip:")), None) if row else None
                    if not row or not observable:
                        raise ValueError("investigation has no IP observable")
                    count = storage.run_investigation_scan(investigation_id=job["investigation_id"], observable_value=observable, time_start=row["time_start"], time_end=row["time_end"])
                    storage.update_investigation_status(job["investigation_id"], "ready")
                    storage.finish_investigation_scan(job["id"], status="complete", result_count=count)
                else:
                    self._stop.wait(1)
            except Exception as exc:
                if job:
                    storage.update_investigation_status(job["investigation_id"], "inconclusive")
                    storage.finish_investigation_scan(job["id"], status="failed", error=str(exc)[:500])
                else:
                    self._stop.wait(1)

worker = Worker()
start = worker.start
stop = worker.stop
