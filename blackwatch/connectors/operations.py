"""Shared connector operation lifecycle.

Runs are persisted as small operational records, while the remote collector
work is performed by bounded worker threads.  A database connection is never
held while a provider call is in progress.  Operation history is append-only;
callers request a bounded recent window when rendering diagnostics.
"""

from __future__ import annotations

import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import storage
from . import runner

MAX_CONCURRENT_OPERATIONS = 3
DEFAULT_OPERATION_TIMEOUT_SECONDS = 120
MAX_RETRY_DELAY_SECONDS = 900

_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_OPERATIONS,
    thread_name_prefix="connector-operation",
)
_state_lock = threading.RLock()
_connector_locks: dict[str, threading.Lock] = {}
_active: dict[str, tuple[str, threading.Lock, Future[Any], threading.Timer]] = {}

_SECRET_RE = re.compile(
    r"(?i)(password|passwd|token|secret|access[_-]?key|authorization)"
    r"(\s*[=:]\s*)([^\s,;]+)"
)
_AWS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_operation(operation: dict[str, Any] | None) -> dict[str, Any] | None:
    if operation is None:
        return None
    result = dict(operation)
    for key in (
        "requested_at", "started_at", "finished_at", "updated_at", "next_attempt_at",
    ):
        result[key] = _iso(result.get(key))
    return result


def _safe_outcome(result: dict[str, Any]) -> dict[str, Any]:
    """Keep collector counters, never raw provider payloads or exceptions."""
    allowed = {
        key: value for key, value in result.items()
        if key in {
            "status", "ingested", "messages", "results", "buckets", "findings",
            "scan_complete", "files_processed", "errors", "since", "targets_checked",
            "ok", "failed",
        }
    }
    safe: dict[str, Any] = {}
    for key, value in allowed.items():
        if isinstance(value, (str, int, float, bool, type(None))):
            safe[key] = value
        elif isinstance(value, (list, dict)):
            safe[key] = {"count": len(value)}
    return safe


def _public_operation(operation: dict[str, Any] | None) -> dict[str, Any] | None:
    # Internal alias keeps the worker code compact while exposing one stable
    # serializer to API and UI callers.
    return serialize_operation(operation)


def get_latest_connector_operations(
    connector_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Return the most recent persisted operation for each connector.

    The API uses this read helper to decorate the connector list. Keep the
    storage boundary here so callers do not need to know how operation rows
    are selected or serialized.
    """
    rows = storage.get_latest_connector_operations(connector_ids)
    return {
        connector_id: serialized
        for connector_id, row in rows.items()
        if (serialized := _public_operation(row)) is not None
    }


def classify_failure(exc: BaseException) -> str:
    """Return a stable, non-sensitive category for operator diagnostics."""
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if isinstance(exc, (ValueError, TypeError)) or "validation" in name:
        return "configuration"
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if any(term in text for term in (
        "accessdenied", "access denied", "invalidclienttoken", "credential",
        "unauthorized", "forbidden", "permission",
    )):
        return "authentication"
    if any(term in text for term in (
        "throttl", "rate exceeded", "too many requests", "quota",
    )):
        return "rate_limited"
    if isinstance(exc, (ConnectionError, OSError)) or any(term in text for term in (
        "connection refused", "connection reset", "unavailable", "dns", "endpoint",
        "no such host",
    )):
        return "unavailable"
    return "unknown"


_FAILURE_GUIDANCE = {
    "configuration": (
        "The connector configuration was rejected before collection completed.",
        "Review the endpoint, queue, region, and interval fields, then test again.",
    ),
    "authentication": (
        "The provider rejected the configured identity or permission.",
        "Verify the mounted profile and least-privilege permissions without entering secrets in BlackWatch.",
    ),
    "rate_limited": (
        "The provider limited this request or account.",
        "Wait for the next backoff window and check provider quota before increasing scope.",
    ),
    "timeout": (
        "The connector did not finish within its safety timeout.",
        "Check provider latency and network reachability; retry after the next backoff window.",
    ),
    "unavailable": (
        "The configured provider or endpoint was not reachable.",
        "Check DNS, routing, security groups, and whether the provider is available.",
    ),
    "unknown": (
        "The connector failed for an unclassified reason.",
        "Open the connector diagnostics and correlate the operation ID with the app log.",
    ),
}


def redact_error(exc: BaseException, category: str | None = None) -> dict[str, str]:
    category = category or classify_failure(exc)
    detail = _SECRET_RE.sub(r"\1\2[redacted]", str(exc))
    detail = _AWS_KEY_RE.sub("[redacted-aws-key]", detail)
    detail = " ".join(detail.split())[:500]
    explanation, next_action = _FAILURE_GUIDANCE.get(category, _FAILURE_GUIDANCE["unknown"])
    return {
        "category": category,
        "message": detail or explanation,
        "explanation": explanation,
        "next_action": next_action,
    }


def compute_retry_delay(retry_count: int, *, jitter: int | None = None) -> int:
    """Conservative exponential backoff, starting at approximately one minute."""
    base = min(MAX_RETRY_DELAY_SECONDS, 60 * (2 ** min(max(0, int(retry_count)), 4)))
    if jitter is None:
        jitter = 0
    return min(MAX_RETRY_DELAY_SECONDS, base + max(0, min(int(jitter), 30)))


def aggregate_progress(children: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "queued": 0, "running": 0, "succeeded": 0, "failed": 0,
        "skipped": 0, "timed_out": 0,
    }
    for child in children:
        status = child.get("status")
        if status in counts:
            counts[status] += 1
    total = len(children)
    completed = counts["succeeded"] + counts["failed"] + counts["skipped"] + counts["timed_out"]
    return {
        "total": total,
        **counts,
        "completed": completed,
        "progress_percent": int((completed * 100) / total) if total else 100,
    }


def _lock_for(connector_id: str) -> threading.Lock:
    with _state_lock:
        return _connector_locks.setdefault(connector_id, threading.Lock())


def _active_result(connector_id: str) -> dict[str, Any] | None:
    try:
        active = storage.find_active_connector_operation(connector_id)
    except Exception:
        active = None
    if active:
        return {
            "accepted": False,
            "duplicate": True,
            "operation": _public_operation(active),
        }
    return None


def start_connector_operation(
    connector_id: str,
    *,
    kind: str = "manual",
    parent_operation_id: str | None = None,
    created_by: str | None = None,
    retry_count: int = 0,
    timeout_seconds: int = DEFAULT_OPERATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    connector = storage.get_connector(connector_id)
    if connector is None:
        return {"accepted": False, "status": "rejected", "error": "connector not found"}
    if kind == "manual" and not connector.get("verified"):
        return {
            "accepted": False, "status": "skipped", "reason": "unverified",
            "connector_id": connector_id,
        }
    if kind == "scheduled" and not (connector.get("enabled") and connector.get("verified")):
        return {
            "accepted": False, "status": "skipped", "reason": "disabled_or_unverified",
            "connector_id": connector_id,
        }

    duplicate = _active_result(connector_id)
    if duplicate:
        return duplicate
    lock = _lock_for(connector_id)
    if not lock.acquire(blocking=False):
        duplicate = _active_result(connector_id)
        return duplicate or {
            "accepted": False, "duplicate": True, "reason": "operation already running",
        }

    operation_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    requested_at = _now()
    try:
        storage.create_connector_operation(
            operation_id,
            kind=kind,
            connector_id=connector_id,
            parent_operation_id=parent_operation_id,
            correlation_id=correlation_id,
            requested_at=requested_at,
            retry_count=retry_count,
            created_by=created_by,
        )
        future = _executor.submit(
            _execute,
            operation_id,
            connector_id,
            kind,
            lock,
            max(1, min(int(timeout_seconds), 900)),
        )
        timer = threading.Timer(
            max(1, min(int(timeout_seconds), 900)),
            _timeout_operation,
            args=(operation_id, connector_id, lock, retry_count),
        )
        timer.daemon = True
        with _state_lock:
            _active[operation_id] = (connector_id, lock, future, timer)
        timer.start()
    except Exception:
        lock.release()
        raise
    operation = storage.get_connector_operation(operation_id)
    return {
        "accepted": True,
        "duplicate": False,
        "operation": _public_operation(operation),
    }


def _finish(operation_id: str, connector_id: str, lock: threading.Lock) -> None:
    with _state_lock:
        current = _active.pop(operation_id, None)
    if current:
        current[3].cancel()
    if lock.locked():
        lock.release()


def _execute(
    operation_id: str,
    connector_id: str,
    kind: str,
    lock: threading.Lock,
    timeout_seconds: int,
) -> None:
    started = _now()
    storage.update_connector_operation(
        operation_id, status="running", started_at=started, attempt=1
    )
    try:
        result = runner.run_connector(connector_id)
        current = storage.get_connector_operation(operation_id)
        if current and current.get("status") == "timed_out":
            return
        duration_ms = int((_now() - started).total_seconds() * 1000)
        if result.get("status") == "ok":
            storage.update_connector_operation(
                operation_id,
                status="succeeded",
                finished_at=_now(),
                duration_ms=duration_ms,
                outcome=_safe_outcome(result),
            )
            storage.set_connector_retry(
                connector_id, retry_count=0, next_attempt_at=None, reason=None
            )
        else:
            _record_failure(operation_id, connector_id, result.get("error", "connector failed"),
                            kind=kind, started=started, duration_ms=duration_ms)
    except Exception as exc:
        current = storage.get_connector_operation(operation_id)
        if current and current.get("status") == "timed_out":
            return
        duration_ms = int((_now() - started).total_seconds() * 1000)
        _record_failure(operation_id, connector_id, exc, kind=kind, started=started,
                        duration_ms=duration_ms)
    finally:
        _finish(operation_id, connector_id, lock)


def _record_failure(
    operation_id: str,
    connector_id: str,
    failure: Any,
    *,
    kind: str,
    started: datetime,
    duration_ms: int,
) -> None:
    exc = failure if isinstance(failure, BaseException) else RuntimeError(str(failure))
    category = classify_failure(exc)
    safe = redact_error(exc, category)
    connector = storage.get_connector(connector_id) or {}
    retry_count = int(connector.get("retry_count") or 0) + 1
    # retry_count is incremented for the failure being recorded. Calculate
    # the delay from the number of failures already seen so the first retry
    # is approximately one minute, then back off exponentially.
    next_attempt = _now() + timedelta(seconds=compute_retry_delay(max(0, retry_count - 1)))
    storage.update_connector_operation(
        operation_id,
        status="failed",
        finished_at=_now(),
        next_attempt_at=next_attempt,
        retry_count=retry_count,
        duration_ms=duration_ms,
        outcome={"status": "error"},
        error_category=category,
        error_message=safe["message"],
    )
    storage.set_connector_retry(
        connector_id,
        retry_count=retry_count,
        next_attempt_at=next_attempt,
        reason=category,
    )


def _timeout_operation(
    operation_id: str,
    connector_id: str,
    lock: threading.Lock,
    retry_count: int,
) -> None:
    with _state_lock:
        current = _active.get(operation_id)
    if not current or current[2].done():
        return
    operation = storage.get_connector_operation(operation_id)
    if not operation or operation.get("status") not in {"queued", "running"}:
        return
    safe = redact_error(TimeoutError("connector operation timed out"), "timeout")
    next_attempt = _now() + timedelta(seconds=compute_retry_delay(retry_count + 1))
    storage.update_connector_operation(
        operation_id,
        status="timed_out",
        finished_at=_now(),
        next_attempt_at=next_attempt,
        retry_count=retry_count + 1,
        error_category="timeout",
        error_message=safe["message"],
        outcome={"status": "timed_out"},
    )
    storage.set_connector_retry(
        connector_id,
        retry_count=retry_count + 1,
        next_attempt_at=next_attempt,
        reason="timeout",
    )


def start_retry_all(
    *,
    scope: str = "eligible",
    created_by: str | None = None,
) -> dict[str, Any]:
    parent_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    storage.create_connector_operation(
        parent_id, kind="retry_all", connector_id=None, correlation_id=correlation_id,
        created_by=created_by,
    )
    children: list[str] = []
    for connector in storage.list_connectors():
        if scope == "eligible" and not (connector.get("enabled") and connector.get("verified")):
            reason = "disabled" if not connector.get("enabled") else "unverified"
            child_id = str(uuid.uuid4())
            children.append(child_id)
            storage.create_connector_operation(
                child_id, kind="retry_all_item", connector_id=connector["id"],
                parent_operation_id=parent_id, correlation_id=str(uuid.uuid4()),
                status="skipped", outcome={"reason": reason}, created_by=created_by,
            )
            continue
        result = start_connector_operation(
            connector["id"], kind="retry_all", parent_operation_id=parent_id,
            created_by=created_by, retry_count=int(connector.get("retry_count") or 0),
        )
        op = result.get("operation") or {}
        if op.get("operation_id"):
            children.append(op["operation_id"])
        else:
            child_id = str(uuid.uuid4())
            children.append(child_id)
            storage.create_connector_operation(
                child_id, kind="retry_all_item", connector_id=connector["id"],
                parent_operation_id=parent_id, correlation_id=str(uuid.uuid4()),
                status="skipped", outcome={"reason": result.get("reason", "duplicate")},
                created_by=created_by,
            )
    child_rows = storage.list_connector_operations(parent_operation_id=parent_id, limit=100)
    progress = aggregate_progress(child_rows)
    status = "succeeded" if progress["completed"] == progress["total"] else "running"
    storage.update_connector_operation(
        parent_id, status=status, outcome=progress,
        finished_at=_now() if status == "succeeded" else None,
    )
    if status != "succeeded":
        thread = threading.Thread(
            target=_monitor_aggregate, args=(parent_id,),
            name=f"connector-aggregate-{parent_id[:8]}", daemon=True,
        )
        thread.start()
    parent = storage.get_connector_operation(parent_id)
    return {
        "accepted": True, "operation": _public_operation(parent),
        "progress": progress,
    }


def _monitor_aggregate(parent_id: str) -> None:
    while True:
        children = storage.list_connector_operations(parent_operation_id=parent_id, limit=100)
        progress = aggregate_progress(children)
        terminal = progress["completed"] == progress["total"]
        status = "succeeded"
        if progress["failed"] or progress["timed_out"]:
            status = "failed"
        elif not terminal:
            status = "running"
        storage.update_connector_operation(
            parent_id, status=status, outcome=progress,
            finished_at=_now() if terminal else None,
        )
        if terminal:
            return
        threading.Event().wait(0.5)


def operation_details(operation_id: str) -> dict[str, Any] | None:
    operation = storage.get_connector_operation(operation_id)
    if operation is None:
        return None
    result = {"operation": serialize_operation(operation)}
    if operation.get("error_category"):
        result["diagnostics"] = _FAILURE_GUIDANCE.get(
            operation["error_category"], _FAILURE_GUIDANCE["unknown"]
        )
    if operation.get("connector_id"):
        result["recent_history"] = [
            serialize_operation(row)
            for row in storage.list_connector_operations(
                connector_id=operation["connector_id"], limit=10
            )
        ]
    if operation.get("kind") == "retry_all":
        result["children"] = [
            serialize_operation(row)
            for row in storage.list_connector_operations(
                parent_operation_id=operation_id, limit=100
            )
        ]
    return result


def recover_stale_operations(max_age_seconds: int = DEFAULT_OPERATION_TIMEOUT_SECONDS) -> int:
    """Close orphaned queued/running rows after a process restart."""
    cutoff = _now() - timedelta(seconds=max_age_seconds)
    recovered = 0
    for operation in storage.list_connector_operations(limit=100):
        if operation.get("status") not in {"queued", "running"}:
            continue
        if (operation.get("updated_at") or operation.get("requested_at") or _now()) > cutoff:
            continue
        safe = redact_error(TimeoutError("orphaned connector operation"), "timeout")
        storage.update_connector_operation(
            operation["operation_id"], status="timed_out", finished_at=_now(),
            error_category="timeout", error_message=safe["message"],
            outcome={"status": "timed_out", "reason": "process_restart"},
        )
        recovered += 1
    return recovered
