"""AWS S3 inventory adapter.

Consumes drift-scan reports — produced either by the in-app `aws_s3_drift`
connector or the standalone `scripts/s3_bucket_inventory.py` bootstrap. Same
shape from both producers:

    {
      "kind": "s3_bucket_snapshot",
      "scanned_at": "2026-06-05T18:00:00Z",
      "scanner_version": "1.0",
      "account": "<account-id>",
      "buckets": [
        {
          "name": "patient-data-prod",
          "region": "us-west-1",
          "created_date": "2025-03-01T12:00:00Z",
          "public": false,
          "public_reasons": [],
          "encryption": "AES256",            # or "aws:kms" or "none"
          "versioning": "Enabled",           # or "Suspended" or "Disabled"
          "mfa_delete": false,
          "block_public_access": {
            "block_public_acls": true, "ignore_public_acls": true,
            "block_public_policy": true, "restrict_public_buckets": true
          },
          "logging": {"enabled": true, "target_bucket": "logs-bucket"},
          "policy": "<raw policy JSON, possibly null>",
          "tags": {"env": "prod"}
        },
        ...
      ],
      "scan_complete": true                  # false if scanner partially failed
    }

Emits:
  * `s3.bucket.snapshot` — one per bucket, projection-only (transition events
    fire from the projection comparing each snapshot to the stored state).
  * `s3.scan.completed` — one per report, projection-only (drives reconciliation
    of "buckets we expected but didn't see this scan" => disappeared).

Adapter is pure. State (which buckets are tracked, which transitioned) lives in
blackwatch/s3/projection.py and bucket_status table."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..event import Category, Event, Outcome, Source, Target, Transport
from .base import Adapter, IngestContext


def _parse_iso(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class AwsS3Adapter(Adapter):
    module = "aws.s3"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict) or raw.get("kind") != "s3_bucket_snapshot":
            return []
        account = raw.get("account")
        scanned_at = _parse_iso(raw.get("scanned_at")) or datetime.now(timezone.utc)
        try:
            transport = Transport(ctx.transport)
        except ValueError:
            transport = Transport.api
        buckets = raw.get("buckets") or []

        def src(region: str | None = None) -> Source:
            return Source(module=self.module, vendor="aws",
                          account=account, region=region, transport=transport)

        events: list[Event] = []
        for b in buckets:
            if not isinstance(b, dict) or not b.get("name"):
                continue
            name = b["name"]
            events.append(Event(
                source=src(b.get("region")),
                event_time=scanned_at,
                category=Category.storage,
                action="s3.bucket.snapshot",
                outcome=Outcome.success,
                target=Target(id=name, type="aws.s3.bucket", name=name),
                extra={
                    "bucket_name": name,
                    "region": b.get("region"),
                    "account": account,
                    "created_date": b.get("created_date"),
                    "public": bool(b.get("public", False)),
                    "public_reasons": b.get("public_reasons") or [],
                    "encryption": b.get("encryption") or "none",
                    "versioning": b.get("versioning") or "Disabled",
                    "mfa_delete": bool(b.get("mfa_delete", False)),
                    "block_public_access": b.get("block_public_access") or {},
                    "logging": b.get("logging") or {},
                    "policy": b.get("policy"),
                    "tags": b.get("tags") or {},
                },
                raw={"kind": "s3_bucket_snapshot", "bucket": name},
            ))

        # The "scan complete" event tells the projection: any bucket we have in
        # bucket_status that wasn't in *this* report has disappeared. Without
        # this signal we'd have to guess whether a missing bucket means it was
        # deleted or just a partial scan failure.
        if raw.get("scan_complete", True):
            events.append(Event(
                source=src(),
                event_time=scanned_at,
                category=Category.storage,
                action="s3.scan.completed",
                outcome=Outcome.success,
                target=Target(id=account or "aws", type="aws.account"),
                extra={
                    "account": account,
                    "bucket_names": [b.get("name") for b in buckets if isinstance(b, dict)],
                    "scanner_version": raw.get("scanner_version"),
                },
                raw={"kind": "s3_scan_completed", "account": account},
            ))
        return events
