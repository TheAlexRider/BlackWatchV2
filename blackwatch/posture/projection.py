"""AWS posture findings projection.

Two responsibilities:
  1. On each `aws.posture.finding` event: upsert posture_findings; emit
     `aws.posture.finding.new` only on insert (or re-open after a previous
     resolve). Subsequent re-scans of the same finding update last_seen
     silently — no event flood.
  2. On each `aws.posture.scan.completed` event: reconcile — any open finding
     in this account that wasn't in this scan has been resolved. Mark
     resolved_at on those rows and emit `aws.posture.finding.resolved` per
     resolved one.

Posture findings are intentionally NOT category=audit (the AwsPostureAdapter
preserves the per-resource-type category for the original event), so rules
written against the existing categories still match these.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Category, Event, Outcome, Source, Target, Transport

_MODULE = "aws.posture"


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    if event.action == "aws.posture.finding":
        return _project_finding(event)
    if event.action == "aws.posture.scan.completed":
        return _project_scan_completed(event)
    return []


def _project_finding(event: Event) -> list[Event]:
    e = event.extra
    fid = e.get("finding_id")
    if not fid:
        return []
    when = event.event_time or datetime.now(timezone.utc)
    is_new = storage.upsert_posture_finding(
        fid,
        resource_id=e.get("resource_id") or "?",
        resource_type=e.get("resource_type") or "?",
        finding_type=e.get("finding_type") or "?",
        severity=e.get("severity") or "medium",
        region=e.get("region"),
        account=e.get("account"),
        evidence=e.get("evidence") or {},
        last_seen=when,
    )
    if not is_new:
        return []
    # First time we've seen this finding (or it was previously resolved and is
    # now back). Emit the alerting event.
    return [_derive(event, "aws.posture.finding.new", e, when)]


def _project_scan_completed(event: Event) -> list[Event]:
    e = event.extra
    account = e.get("account")
    if not account:
        return []
    seen_ids = set(e.get("finding_ids") or [])
    when = event.event_time or datetime.now(timezone.utc)
    derived: list[Event] = []
    for fid in storage.list_unresolved_finding_ids_for_account(account):
        if fid in seen_ids:
            continue
        prev = storage.get_posture_finding(fid)
        if not prev:
            continue
        storage.mark_posture_finding_resolved(fid, when)
        derived.append(_derive(event, "aws.posture.finding.resolved", {
            "finding_id": fid,
            "resource_id": prev["resource_id"],
            "resource_type": prev["resource_type"],
            "finding_type": prev["finding_type"],
            "severity": prev["severity"],
            "region": prev["region"],
            "account": prev["account"],
        }, when))
    return derived


def _derive(parent: Event, action: str, extras: dict[str, Any], when: datetime) -> Event:
    category = parent.category  # carry through the resource-specific category
    return Event(
        source=Source(module=_MODULE, vendor="aws",
                      account=extras.get("account") or parent.source.account,
                      region=extras.get("region") or parent.source.region,
                      transport=Transport.api),
        event_time=when,
        category=category,
        action=action,
        outcome=Outcome.success if action.endswith("resolved") else Outcome.failure,
        target=Target(
            id=extras.get("resource_id") or "?",
            type=f"aws.{extras.get('resource_type', 'resource')}",
            name=extras.get("resource_id"),
        ),
        extra=extras,
        raw={"derived_from": parent.action, "module": _MODULE},
    )
