import threading
from datetime import datetime, timedelta, timezone

import blackwatch.connectors.operations as connector_operations
import blackwatch.connectors.runner as connector_runner
from blackwatch.connectors.operations import (
    aggregate_progress,
    classify_failure,
    compute_retry_delay,
    get_latest_connector_operations,
    redact_error,
)
from blackwatch.connectors.scheduler import (
    _due,
    _reconcile_retry_metadata,
    connector_health_state,
    retry_due,
)


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def test_latest_connector_operations_delegates_and_serializes(monkeypatch):
    row = {
        "connector_id": "c1",
        "requested_at": NOW,
        "started_at": None,
        "finished_at": None,
        "updated_at": NOW,
        "next_attempt_at": None,
    }
    monkeypatch.setattr(
        "blackwatch.connectors.operations.storage.get_latest_connector_operations",
        lambda ids: {"c1": row} if ids == ["c1"] else {},
    )

    result = get_latest_connector_operations(["c1"])

    assert result["c1"]["requested_at"] == NOW.isoformat()


def test_serializer_accepts_string_timestamps():
    from blackwatch.connectors.operations import serialize_operation

    result = serialize_operation({"requested_at": "2026-09-04T00:00:00+00:00"})

    assert result["requested_at"] == "2026-09-04T00:00:00+00:00"


def test_failure_details_are_safe_and_actionable():
    category = classify_failure(ValueError("token=super-secret queue is invalid"))
    safe = redact_error(ValueError("token=super-secret queue is invalid"), category)

    assert category == "configuration"
    assert "super-secret" not in safe["message"]
    assert safe["category"] == "configuration"
    assert safe["next_action"]
    assert len(safe["message"]) <= 500


def test_retry_delay_is_bounded_and_has_one_minute_base():
    assert compute_retry_delay(0, jitter=0) == 60
    assert compute_retry_delay(1, jitter=0) == 120
    assert compute_retry_delay(99, jitter=0) == 900
    assert 60 <= compute_retry_delay(0, jitter=12) <= 72


def test_connector_health_state_distinguishes_operational_states():
    base = {
        "enabled": True,
        "verified": True,
        "config": {"interval_seconds": 60},
        "last_run_at": NOW - timedelta(seconds=30),
        "last_status": "ok",
    }

    assert connector_health_state({**base, "enabled": False}, now=NOW) == "disabled"
    assert connector_health_state({**base, "verified": False}, now=NOW) == "unverified"
    assert connector_health_state({**base, "last_run_at": None}, now=NOW) == "never_run"
    assert connector_health_state({**base, "operation_status": "running"}, now=NOW) == "running"
    assert connector_health_state({**base, "last_status": "error"}, now=NOW) == "failing"
    assert connector_health_state(
        {**base, "last_run_at": NOW - timedelta(seconds=121)}, now=NOW
    ) == "stale"
    assert connector_health_state(base, now=NOW) == "healthy"


def test_retry_due_excludes_disabled_unverified_and_running_connectors():
    base = {
        "enabled": True,
        "verified": True,
        "config": {"interval_seconds": 60},
        "last_run_at": NOW - timedelta(seconds=300),
        "last_status": "error",
        "retry_count": 0,
        "next_attempt_at": None,
    }

    assert retry_due(base, now=NOW)
    assert not retry_due({**base, "enabled": False}, now=NOW)
    assert not retry_due({**base, "verified": False}, now=NOW)
    assert not retry_due({**base, "operation_status": "queued"}, now=NOW)
    assert not retry_due({**base, "next_attempt_at": NOW + timedelta(seconds=1)}, now=NOW)


def test_failed_connector_uses_retry_backoff_instead_of_full_poll_interval():
    connector = {
        "enabled": True,
        "verified": True,
        "config": {"interval_seconds": 3600},
        "last_run_at": NOW - timedelta(seconds=70),
        "last_status": "error",
        "retry_count": 1,
        "next_attempt_at": NOW - timedelta(seconds=1),
    }

    assert retry_due(connector, now=NOW)
    assert connector_health_state(connector, now=NOW) == "failing"


def test_never_run_connector_honors_a_future_recovery_attempt():
    connector = {
        "enabled": True,
        "verified": True,
        "config": {"interval_seconds": 60},
        "last_run_at": None,
        "last_status": None,
        "scheduler_reason": "process_restart",
        "next_attempt_at": NOW + timedelta(seconds=30),
    }

    assert not _due(connector, now=NOW)
    assert _due(connector, now=NOW + timedelta(seconds=31))


def test_scheduler_repairs_retry_metadata_from_terminal_operation(monkeypatch):
    connector = {
        "id": "c1",
        "retry_count": 2,
        "next_attempt_at": NOW + timedelta(seconds=30),
        "scheduler_reason": "timeout",
    }
    calls = []
    monkeypatch.setattr(
        connector_operations.storage,
        "set_connector_retry",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    _reconcile_retry_metadata(
        connector,
        {"status": "succeeded", "outcome": {}, "next_attempt_at": None},
    )

    assert connector["retry_count"] == 0
    assert connector["next_attempt_at"] is None
    assert connector["scheduler_reason"] is None
    assert calls[0][1] == {
        "retry_count": 0,
        "next_attempt_at": None,
        "reason": None,
    }


def test_aggregate_progress_counts_child_states():
    result = aggregate_progress(
        [
            {"status": "queued"},
            {"status": "running"},
            {"status": "succeeded"},
            {"status": "failed"},
            {"status": "skipped"},
            {"status": "timed_out"},
        ]
    )

    assert result == {
        "total": 6,
        "queued": 1,
        "running": 1,
        "succeeded": 1,
        "failed": 1,
        "skipped": 1,
        "timed_out": 1,
        "completed": 4,
        "progress_percent": 66,
    }


def test_timeout_detaches_worker_and_releases_connector_slot(monkeypatch):
    operation_id = "op-timeout"
    lock = threading.Lock()
    assert lock.acquire(blocking=False)
    assert connector_operations._operation_slots.acquire(blocking=False)
    future = _PendingFuture()
    timer = _TimerStub()
    with connector_operations._state_lock:
        connector_operations._active[operation_id] = ("c1", lock, future, timer)

    updates = []
    retries = []
    monkeypatch.setattr(
        connector_operations.storage,
        "get_connector_operation",
        lambda _operation_id: {"operation_id": operation_id, "status": "running"},
    )
    monkeypatch.setattr(
        connector_operations.storage,
        "mark_connector_operation_timed_out",
        lambda *args, **kwargs: (updates.append((args, kwargs)) or True),
    )
    monkeypatch.setattr(
        connector_operations.storage,
        "set_connector_retry",
        lambda *args, **kwargs: retries.append((args, kwargs)),
    )

    try:
        connector_operations._timeout_operation(operation_id, "c1", lock, 0)

        assert operation_id not in connector_operations._active
        assert not lock.locked()
        assert future.cancel_called
        assert timer.cancel_called
        assert updates[0][1]["retry_count"] == 1
        assert retries[0][1]["reason"] == "timeout"
    finally:
        with connector_operations._state_lock:
            connector_operations._active.pop(operation_id, None)


def test_late_timed_out_worker_cannot_release_new_operation_lock(monkeypatch):
    operation_id = "op-old"
    lock = threading.Lock()
    assert lock.acquire(blocking=False)
    assert connector_operations._operation_slots.acquire(blocking=False)
    future = _PendingFuture()
    timer = _TimerStub()
    with connector_operations._state_lock:
        connector_operations._active[operation_id] = ("c1", lock, future, timer)

    monkeypatch.setattr(
        connector_operations.storage,
        "get_connector_operation",
        lambda _operation_id: {"operation_id": operation_id, "status": "running"},
    )
    monkeypatch.setattr(connector_operations.storage, "mark_connector_operation_timed_out", lambda *a, **k: True)
    monkeypatch.setattr(connector_operations.storage, "set_connector_retry", lambda *a, **k: None)

    try:
        connector_operations._timeout_operation(operation_id, "c1", lock, 0)
        assert lock.acquire(blocking=False)
        connector_operations._finish(operation_id, "c1", lock)
        assert lock.locked()
    finally:
        if lock.locked():
            lock.release()
        with connector_operations._state_lock:
            connector_operations._active.pop(operation_id, None)


def test_restart_recovery_schedules_a_bounded_retry(monkeypatch):
    old = NOW - timedelta(seconds=connector_operations.DEFAULT_OPERATION_TIMEOUT_SECONDS + 1)
    updates = []
    retries = []
    monkeypatch.setattr(
        connector_operations.storage,
        "list_stale_connector_operations",
        lambda _before: [{
            "operation_id": "orphan",
            "connector_id": "c1",
            "status": "running",
            "updated_at": old,
            "requested_at": old,
            "retry_count": 0,
        }],
    )
    monkeypatch.setattr(
        connector_operations.storage,
        "mark_connector_operation_timed_out",
        lambda *args, **kwargs: (updates.append((args, kwargs)) or True),
    )
    monkeypatch.setattr(
        connector_operations.storage,
        "set_connector_retry",
        lambda *args, **kwargs: retries.append((args, kwargs)),
    )
    monkeypatch.setattr(connector_operations, "_now", lambda: NOW)

    assert connector_operations.recover_stale_operations() == 1
    assert updates[0][1]["retry_count"] == 1
    assert retries[0][1]["retry_count"] == 1
    assert retries[0][1]["reason"] == "process_restart"
    assert retries[0][1]["next_attempt_at"] >= NOW + timedelta(seconds=60)


def test_start_rejects_work_when_global_worker_limit_is_reached(monkeypatch):
    active_ids = ["op-1", "op-2", "op-3"]
    locks = []
    with connector_operations._state_lock:
        for operation_id in active_ids:
            lock = threading.Lock()
            assert lock.acquire(blocking=False)
            assert connector_operations._operation_slots.acquire(blocking=False)
            locks.append(lock)
            connector_operations._active[operation_id] = (
                "active-connector", lock, _PendingFuture(), _TimerStub()
            )

    monkeypatch.setattr(
        connector_operations.storage,
        "get_connector",
        lambda _connector_id: {"id": "waiting", "enabled": True, "verified": True},
    )
    monkeypatch.setattr(
        connector_operations.storage,
        "find_active_connector_operation",
        lambda _connector_id: None,
    )

    try:
        result = connector_operations.start_connector_operation("waiting")
        assert result == {
            "accepted": False,
            "duplicate": False,
            "reason": "concurrency_limit",
            "status": "queued",
            "connector_id": "waiting",
        }
        assert connector_operations.active_operation_count() == 3
    finally:
        with connector_operations._state_lock:
            for operation_id, lock in zip(active_ids, locks):
                connector_operations._active.pop(operation_id, None)
                connector_operations._operation_slots.release()
                if lock.locked():
                    lock.release()


def test_late_provider_response_does_not_overwrite_timed_out_connector(monkeypatch):
    monkeypatch.setattr(
        connector_runner.storage,
        "get_connector",
        lambda _connector_id: {
            "id": "c1",
            "type": "aws_cloudtrail_sqs",
            "config": {
                "queue_url": "https://sqs.us-west-1.amazonaws.com/123/queue",
                "target_module": "ec2.host",
            },
        },
    )
    monkeypatch.setattr(
        connector_runner.aws_sqs,
        "drain",
        lambda _cfg: {"ingested": 0, "messages": 1},
    )
    monkeypatch.setattr(
        connector_runner.storage,
        "get_connector_operation",
        lambda _operation_id: {"status": "timed_out"},
    )
    status_updates = []
    monkeypatch.setattr(
        connector_runner.storage,
        "set_connector_status",
        lambda *args, **kwargs: status_updates.append((args, kwargs)),
    )

    result = connector_runner.run_connector("c1", operation_id="op-timeout")

    assert result == {"status": "ok", "ingested": 0, "messages": 1}
    assert status_updates == []


class _PendingFuture:
    cancel_called = False

    def done(self):
        return False

    def cancel(self):
        self.cancel_called = True
        return True


class _TimerStub:
    cancel_called = False

    def cancel(self):
        self.cancel_called = True
