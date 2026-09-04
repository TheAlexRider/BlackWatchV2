"""Run a connector: collect from the remote source, feed the result through the
shared ingest pipeline, and record status. A successful run marks the connector
`verified` (which is what unlocks Run-now / scheduling in the UI)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from . import (
    aws_api_gw_sqs, aws_ecs, aws_ecs_probe_sqs, aws_posture_drift,
    aws_rds_sqs, aws_s3_access_pull, aws_s3_drift, aws_sqs, cert_probe,
)
from .models import (
    AwsApiGwSqsConfig, AwsCloudtrailSqsConfig, AwsEcsHealthConfig,
    AwsEcsProbeSqsConfig, AwsPostureDriftConfig, AwsRdsSqsConfig,
    AwsS3AccessLogsConfig, AwsS3DriftConfig, CertProbeConfig,
)


def _operation_is_live(operation_id: str | None) -> bool:
    """Prevent a late provider response from overwriting a timed-out run."""
    if operation_id is None:
        return True
    try:
        operation = storage.get_connector_operation(operation_id)
    except Exception:
        # A transient diagnostics read must not turn a successful provider
        # call into a connector failure. The operation manager still owns the
        # terminal transition.
        return True
    return bool(operation and operation.get("status") in {"queued", "running"})


def run_connector(
    connector_id: str, *, operation_id: str | None = None
) -> dict[str, Any]:
    connector = storage.get_connector(connector_id)
    if connector is None:
        return {"status": "error", "error": "connector not found"}

    now = datetime.now(timezone.utc)
    ctype = connector["type"]
    try:
        if ctype == "aws_cloudtrail_sqs":
            cfg = AwsCloudtrailSqsConfig(**connector["config"])
            stats = aws_sqs.drain(cfg)
            outcome = {"ingested": stats["ingested"], "messages": stats["messages"]}
        elif ctype == "aws_ecs_health":
            cfg = AwsEcsHealthConfig(**connector["config"])
            stats = aws_ecs.poll(cfg)
            outcome = {"ingested": stats["ingested"], "results": stats["results"]}
        elif ctype == "aws_ecs_probe_sqs":
            cfg = AwsEcsProbeSqsConfig(**connector["config"])
            stats = aws_ecs_probe_sqs.drain(cfg)
            outcome = {"ingested": stats["ingested"], "messages": stats["messages"]}
        elif ctype == "aws_rds_sqs":
            cfg = AwsRdsSqsConfig(**connector["config"])
            stats = aws_rds_sqs.drain(cfg)
            outcome = {"ingested": stats["ingested"], "messages": stats["messages"]}
        elif ctype == "aws_api_gw_sqs":
            cfg = AwsApiGwSqsConfig(**connector["config"])
            stats = aws_api_gw_sqs.drain(cfg)
            outcome = {"ingested": stats["ingested"], "messages": stats["messages"]}
        elif ctype == "aws_s3_drift":
            cfg = AwsS3DriftConfig(**connector["config"])
            stats = aws_s3_drift.poll(cfg)
            outcome = {"ingested": stats["ingested"],
                       "buckets": stats["buckets"],
                       "scan_complete": stats["scan_complete"]}
        elif ctype == "aws_s3_access_logs":
            cfg = AwsS3AccessLogsConfig(**connector["config"])
            stats = aws_s3_access_pull.poll(cfg)
            outcome = {"ingested": stats["ingested"],
                       "files_processed": stats["files_processed"],
                       "errors": stats["errors"],
                       "since": stats["since"]}
        elif ctype == "aws_posture_drift":
            cfg = AwsPostureDriftConfig(**connector["config"])
            stats = aws_posture_drift.poll(cfg)
            outcome = {"ingested": stats["ingested"],
                       "findings": stats["findings"],
                       "scan_complete": stats["scan_complete"],
                       "errors": stats["errors"]}
        elif ctype == "cert_probe":
            cfg = CertProbeConfig(**connector["config"])
            stats = cert_probe.poll(cfg)
            outcome = {"ingested": stats["ingested"],
                       "targets_checked": stats["targets_checked"],
                       "ok": stats["ok"],
                       "failed": stats["failed"]}
        else:
            raise RuntimeError(f"unknown connector type: {ctype}")

        if _operation_is_live(operation_id):
            storage.set_connector_status(
                connector_id, last_status="ok", last_error=None,
                last_run_at=now, verified=True, operation_id=operation_id,
            )
        return {"status": "ok", **outcome}
    except Exception as exc:
        if _operation_is_live(operation_id):
            storage.set_connector_status(
                connector_id, last_status="error", last_error=str(exc),
                last_run_at=now, operation_id=operation_id,
            )
        return {"status": "error", "error": str(exc)}
