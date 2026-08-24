"""Derived collector coverage data for the operator overview.

The coverage view deliberately does not create a second health registry. It
normalizes the existing connector status into a small, read-only model that
can be consumed by the API and UI without a migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


_DEFAULT_STALE_AFTER_SECONDS = 900

_TYPE_MODULES = {
    "aws_cloudtrail_sqs": "aws.cloudtrail",
    "aws_ecs_health": "aws.ecs",
    "aws_rds_sqs": "aws.rds",
    "aws_api_gw_sqs": "aws.api_gateway",
    "aws_s3_drift": "aws.s3",
    "aws_posture_drift": "aws.posture",
    "cert_probe": "probe.cert",
}

_MODULE_LINKS = {
    "aws.cloudtrail": "/events",
    "aws.ecs": "/services",
    "aws.rds": "/rds",
    "aws.api_gateway": "/api-gw",
    "aws.s3": "/buckets",
    "aws.posture": "/aws-posture",
    "probe.cert": "/services",
}


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _module_for(row: dict[str, Any]) -> str:
    config = row.get("config") or {}
    configured = config.get("target_module")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return _TYPE_MODULES.get(str(row.get("type") or ""), "unknown")


def _interval_seconds(row: dict[str, Any]) -> int:
    config = row.get("config") or {}
    try:
        interval = int(config.get("interval_seconds", _DEFAULT_STALE_AFTER_SECONDS))
    except (TypeError, ValueError):
        interval = _DEFAULT_STALE_AFTER_SECONDS
    return max(interval, 1)


def _status(row: dict[str, Any], now: datetime) -> tuple[str, str]:
    if not row.get("enabled", False):
        return "disabled", "collector is disabled"

    last_status = str(row.get("last_status") or "").lower()
    if last_status in {"error", "failed", "failure", "down"} or row.get("last_error"):
        return "failing", "last collector run failed"
    if not row.get("verified", False):
        return "unverified", "collector has not passed verification"

    last_run = _as_datetime(row.get("last_run_at"))
    if last_run is None:
        return "stale", "collector has never completed a run"

    age_seconds = max(0, int((now - last_run).total_seconds()))
    stale_after = max(_DEFAULT_STALE_AFTER_SECONDS, _interval_seconds(row) * 3)
    if age_seconds > stale_after:
        return "stale", f"last run is {age_seconds}s old"
    if last_status not in {"", "ok", "success", "healthy"}:
        return "failing", f"unexpected last status: {last_status}"
    return "healthy", "last run succeeded"


def build_coverage_summary(
    connectors: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the API-safe coverage model from connector records."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []

    for connector in connectors:
        module = _module_for(connector)
        status, reason = _status(connector, current)
        last_seen = _as_datetime(connector.get("last_run_at"))
        rows.append(
            {
                "source": str(connector.get("type") or "unknown"),
                "module": module,
                "module_href": _MODULE_LINKS.get(module, "/events"),
                "connector_id": str(connector.get("id") or ""),
                "connector_name": str(connector.get("name") or connector.get("id") or "Unnamed"),
                "enabled": bool(connector.get("enabled", False)),
                "verified": bool(connector.get("verified", False)),
                "last_seen_event": last_seen.isoformat() if last_seen else None,
                "status": status,
                "stale": status == "stale",
                "failing": status == "failing",
                "reason": reason,
            }
        )

    counts = {name: sum(1 for row in rows if row["status"] == name) for name in (
        "healthy", "stale", "failing", "unverified", "disabled"
    )}
    counts["attention"] = counts["stale"] + counts["failing"] + counts["unverified"]
    counts["total"] = len(rows)

    return {
        "now": current.isoformat(),
        "freshness_basis": "connector_last_run",
        "stale_after_seconds": _DEFAULT_STALE_AFTER_SECONDS,
        "summary": counts,
        "coverage": rows,
        "zero_event_semantics": (
            "A healthy connector means its last run succeeded; zero events "
            "ingested is not treated as missing coverage in this version."
        ),
    }
