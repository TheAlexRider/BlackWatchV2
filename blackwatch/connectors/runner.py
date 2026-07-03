"""Run a connector: collect from the remote source, feed the result through the
shared ingest pipeline, and record status. A successful run marks the connector
`verified` (which is what unlocks Run-now / scheduling in the UI)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from . import (
    aws_ecs, aws_ecs_probe_sqs, aws_posture_drift, aws_rds_sqs,
    aws_s3_drift, aws_sqs, cert_probe,
)
from .models import (
    AwsCloudtrailSqsConfig, AwsEcsHealthConfig, AwsEcsProbeSqsConfig,
    AwsPostureDriftConfig, AwsRdsSqsConfig, AwsS3DriftConfig,
    CertProbeConfig,
)


def run_connector(connector_id: str) -> dict[str, Any]:
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
        elif ctype == "aws_s3_drift":
            cfg = AwsS3DriftConfig(**connector["config"])
            stats = aws_s3_drift.poll(cfg)
            outcome = {"ingested": stats["ingested"],
                       "buckets": stats["buckets"],
                       "scan_complete": stats["scan_complete"]}
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

        storage.set_connector_status(
            connector_id, last_status="ok", last_error=None, last_run_at=now, verified=True
        )
        return {"status": "ok", **outcome}
    except Exception as exc:
        storage.set_connector_status(
            connector_id, last_status="error", last_error=str(exc), last_run_at=now
        )
        return {"status": "error", "error": str(exc)}
