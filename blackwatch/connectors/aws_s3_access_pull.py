"""S3 Server Access Log pull connector.

Every N seconds, list objects in the central log bucket whose LastModified
crosses the (last_run_at - overlap_seconds) threshold, download each,
and feed the file contents to the aws.s3.access adapter via pipeline.ingest_payload.

Cursor is TIME-based (LastModified) so no schema changes needed for state:
we rely on the connector row's `last_run_at` that the runner already updates
on success. Dedupe is handled downstream by deterministic event_ids +
ON CONFLICT DO NOTHING in storage.insert_event.

IAM: the runtime credential must be scoped to `s3:ListBucket` + `s3:GetObject`
on the log bucket ONLY. See docs/iam-policies/bw-s3-access-logs-reader.json.
Preferred: attach the policy to the BW EC2 instance role — boto3 picks it up
via IMDS with no explicit credential handoff.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import pipeline, storage
from .models import AwsS3AccessLogsConfig


def _client(cfg: AwsS3AccessLogsConfig):
    import boto3
    session = boto3.session.Session(
        profile_name=cfg.aws_profile or None,
        region_name=cfg.aws_region,
    )
    return session.client("s3")


def _source_bucket_from_key(key: str, prefix: str) -> str:
    """Access log keys under this convention:
        logs/<source-bucket>/YYYY-MM-DD-HH-MM-SS-XXXXXXXXXX

    Return the <source-bucket> segment. `prefix` is applied first if set
    (letting operators run one connector per bucket-group)."""
    tail = key[len(prefix):] if prefix and key.startswith(prefix) else key
    # Strip a leading "logs/" if present (matches Script 2's TargetPrefix).
    if tail.startswith("logs/"):
        tail = tail[len("logs/"):]
    slash = tail.find("/")
    return tail[:slash] if slash > 0 else "unknown"


def poll(cfg: AwsS3AccessLogsConfig) -> dict[str, Any]:
    """Pull one batch of new log objects and ship them through ingest_payload.
    Returns a stats dict the runner records on the connector row."""
    now = datetime.now(timezone.utc)

    # Time cursor: the runner already writes last_run_at on every success. Look
    # it up by finding the connector row for this config (cheap — small table).
    # If no run yet, use `now - overlap` so we start with only recent files
    # rather than replaying the whole 3-day retention on first ever run.
    last_run = _last_run_at(cfg.bucket)
    since = (last_run or now - timedelta(seconds=cfg.overlap_seconds))
    since -= timedelta(seconds=cfg.overlap_seconds)  # overlap buffer

    s3 = _client(cfg)
    paginator = s3.get_paginator("list_objects_v2")

    processed = 0
    ingested = 0
    errors = 0
    skipped_empty = 0
    for page in paginator.paginate(Bucket=cfg.bucket, Prefix=cfg.prefix or ""):
        for obj in page.get("Contents") or []:
            if processed >= cfg.max_files_per_run:
                break
            key = obj.get("Key")
            last_mod = obj.get("LastModified")
            if not key or not last_mod:
                continue
            if last_mod < since:
                continue
            try:
                body = s3.get_object(Bucket=cfg.bucket, Key=key)["Body"].read()
            except Exception:
                errors += 1
                continue
            processed += 1
            if not body:
                skipped_empty += 1
                continue
            try:
                content = body.decode("utf-8", errors="replace")
            except Exception:
                errors += 1
                continue
            source_bucket = _source_bucket_from_key(key, cfg.prefix or "")
            payload = {
                "kind": "s3_access_log_batch",
                "log_bucket": cfg.bucket,
                "log_key": key,
                "source_bucket": source_bucket,
                "content": content,
            }
            try:
                result = pipeline.ingest_payload(
                    module="aws.s3.access",
                    raw=payload,
                    transport="poll",
                    region=cfg.aws_region,
                )
                ingested += int(result.get("ingested", 0)) + int(result.get("transient", 0))
            except Exception:
                errors += 1
        if processed >= cfg.max_files_per_run:
            break

    return {
        "ingested": ingested,
        "files_processed": processed,
        "empty": skipped_empty,
        "errors": errors,
        "since": since.isoformat(),
    }


def _last_run_at(bucket: str) -> datetime | None:
    """Look up the last successful run timestamp for THIS connector.
    Matching by config.bucket rather than connector_id so callers of poll()
    (both the scheduler and manual Run-now) share the same cursor."""
    for c in storage.list_connectors():
        if c.get("type") != "aws_s3_access_logs":
            continue
        if (c.get("config") or {}).get("bucket") != bucket:
            continue
        return c.get("last_run_at")
    return None
