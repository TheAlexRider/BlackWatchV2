from datetime import datetime, timedelta, timezone

from blackwatch.connectors.operations import (
    aggregate_progress,
    classify_failure,
    compute_retry_delay,
    get_latest_connector_operations,
    redact_error,
)
from blackwatch.connectors.scheduler import connector_health_state, retry_due


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
