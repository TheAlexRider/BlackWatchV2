"""AWS posture findings adapter.

Consumes the drift-scan report produced by `connectors/aws_posture_drift.py`:

    {
      "kind": "aws_posture_report",
      "scanned_at": "2026-06-05T18:00:00Z",
      "scanner_version": "1.0",
      "account": "111122223333",
      "checks_run": ["sg_public_ingress", "ebs_encryption", ...],
      "findings": [
        {
          "resource_id": "sg-abc123",
          "resource_type": "sg",
          "finding_type": "public_ingress_risky_port",
          "severity": "critical",
          "region": "us-west-1",
          "evidence": {"ports": [22], "cidrs": ["0.0.0.0/0"], "vpc_id": "vpc-x"}
        },
        ...
      ],
      "scan_complete": true
    }

Emits:
  * aws.posture.finding — one per finding entry (projection-only). The
    projection upserts into posture_findings and emits aws.posture.finding.new
    only on the first appearance (or re-open after a resolve).
  * aws.posture.scan.completed — one per report when scan_complete=True. The
    projection uses it to reconcile: any open finding in this account that
    wasn't in this scan has been resolved.

Adapter is pure. Finding lifecycle (new/resolved/re-opened) lives in
blackwatch/posture/projection.py."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from ..event import Category, Event, Outcome, Severity, Source, Target, Transport
from .base import Adapter, IngestContext


def finding_id(account: str | None, resource_id: str, finding_type: str) -> str:
    """Deterministic ID for upsert + dedup. Same input → same ID across scans."""
    blob = f"{account or '-'}|{resource_id}|{finding_type}"
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def _parse_iso(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# Map finding severity string → Severity enum. Defensive: anything else falls
# back to medium so a typo doesn't drop a finding.
_SEV_MAP = {
    "critical": Severity.critical, "high": Severity.high,
    "medium": Severity.medium, "low": Severity.low,
    "informational": Severity.informational,
}


# Resource type → BlackWatch category for the events. Posture findings span
# multiple categories — we keep the original event-envelope category right.
_CATEGORY_FOR_RESOURCE = {
    "sg": Category.network,
    "ec2_instance": Category.compute,
    "ami": Category.compute,
    "ebs_volume": Category.storage,
    "ebs_snapshot": Category.storage,
    "iam_user": Category.iam,
    "iam_access_key": Category.iam,
    "iam_role": Category.iam,
    "kms_key": Category.iam,
    "cloudtrail": Category.audit,
}


class AwsPostureAdapter(Adapter):
    module = "aws.posture"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict) or raw.get("kind") != "aws_posture_report":
            return []
        account = raw.get("account")
        scanned_at = _parse_iso(raw.get("scanned_at")) or datetime.now(timezone.utc)
        try:
            transport = Transport(ctx.transport)
        except ValueError:
            transport = Transport.api

        def src(region: str | None = None) -> Source:
            return Source(module=self.module, vendor="aws",
                          account=account, region=region, transport=transport)

        events: list[Event] = []
        findings = raw.get("findings") or []
        for f in findings:
            if not isinstance(f, dict):
                continue
            rid, rtype, ftype = f.get("resource_id"), f.get("resource_type"), f.get("finding_type")
            if not (rid and rtype and ftype):
                continue
            severity = _SEV_MAP.get(f.get("severity", "medium"), Severity.medium)
            category = _CATEGORY_FOR_RESOURCE.get(rtype, Category.audit)
            fid = finding_id(account, rid, ftype)
            events.append(Event(
                source=src(f.get("region")),
                event_time=scanned_at,
                category=category,
                action="aws.posture.finding",
                # All findings represent SOMETHING WRONG with posture — `failure`.
                outcome=Outcome.failure,
                target=Target(id=rid, type=f"aws.{rtype}", name=rid),
                severity=severity,
                extra={
                    "finding_id": fid,
                    "resource_id": rid,
                    "resource_type": rtype,
                    "finding_type": ftype,
                    "severity": f.get("severity", "medium"),
                    "region": f.get("region"),
                    "account": account,
                    "evidence": f.get("evidence") or {},
                },
                raw={"kind": "aws_posture_finding", "finding_id": fid},
            ))

        # The completion marker enables reconciliation. Same partial-scan safety
        # as the S3 module — only emit when scan_complete=True so a crashed
        # scan never marks all findings resolved.
        if raw.get("scan_complete", True):
            events.append(Event(
                source=src(),
                event_time=scanned_at,
                category=Category.audit,
                action="aws.posture.scan.completed",
                outcome=Outcome.success,
                target=Target(id=account or "aws", type="aws.account"),
                extra={
                    "account": account,
                    "finding_ids": [
                        finding_id(account, f["resource_id"], f["finding_type"])
                        for f in findings if isinstance(f, dict)
                        and f.get("resource_id") and f.get("finding_type")
                    ],
                    "checks_run": raw.get("checks_run") or [],
                    "scanner_version": raw.get("scanner_version"),
                },
                raw={"kind": "aws_posture_scan_completed", "account": account},
            ))
        return events
