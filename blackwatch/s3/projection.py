"""S3 bucket-inventory projection.

Two responsibilities:
  1. On each `s3.bucket.snapshot` event: upsert bucket_status; compare the new
     state to what we had stored; emit transition events for anything that
     changed (became public, encryption removed, versioning suspended, …) and
     `s3.bucket.first_seen` if this is the first time we've seen the bucket.
     The first-ever scan for a *bucket* baselines silently (no first_seen
     storm) — the rule for first_seen targets newly-appearing buckets after
     baseline.
  2. On each `s3.scan.completed` event: reconcile — any bucket BW has tracked
     for this account that *wasn't* in this scan has disappeared. Emit
     `s3.bucket.disappeared` and delete the row.

Transition events are stored + notify. Snapshots themselves are not stored
(projection-only in pipeline.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Category, Event, Outcome, Source, Target, Transport

_MODULE = "aws.s3"


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    if event.action == "s3.bucket.snapshot":
        return _project_snapshot(event)
    if event.action == "s3.scan.completed":
        return _project_scan_completed(event)
    return []


# ---------- s3.bucket.snapshot ----------------------------------------------

def _project_snapshot(event: Event) -> list[Event]:
    e = event.extra
    name = e.get("bucket_name")
    if not name:
        return []
    when = event.event_time or datetime.now(timezone.utc)
    prev = storage.get_bucket_status(name)
    is_first_ever_for_bucket = prev is None

    # Normalize the incoming side once.
    new_public = bool(e.get("public", False))
    new_public_reasons = e.get("public_reasons") or []
    new_encryption = e.get("encryption") or "none"
    new_versioning = e.get("versioning") or "Disabled"
    new_mfa_delete = bool(e.get("mfa_delete", False))
    new_bpa = e.get("block_public_access") or {}
    new_logging = e.get("logging") or {}
    logging_target = new_logging.get("target_bucket") if new_logging.get("enabled") else None
    policy = e.get("policy")
    # Truncate huge policies before storage — UI shows first 16k.
    if isinstance(policy, str) and len(policy) > 16_000:
        policy = policy[:16_000] + "...[truncated]"
    tags = e.get("tags") or {}

    storage.upsert_bucket_status(
        name,
        region=e.get("region"), account=e.get("account"),
        created_date=_parse_iso(e.get("created_date")), last_scan=when,
        public=new_public, public_reasons=new_public_reasons,
        encryption=new_encryption, versioning=new_versioning,
        mfa_delete=new_mfa_delete,
        block_public_access=new_bpa,
        logging_target=logging_target, policy=policy,
        tags=tags, extra={},
    )

    derived: list[Event] = []

    def emit(action: str, severity_hint: str | None = None, **extras: Any) -> None:
        derived.append(_make_derived(event, name, action, extras, when))

    if is_first_ever_for_bucket:
        # Baseline silently: emit ONLY a first_seen event so operators see new
        # buckets appearing, but DON'T emit "now public" / "no encryption" etc.
        # on the first scan — those are baseline state, not changes.
        emit("s3.bucket.first_seen",
             region=e.get("region"), account=e.get("account"),
             public=new_public, encryption=new_encryption,
             versioning=new_versioning)
        # However, if the bucket is ALREADY public on first sight, that's
        # high-signal — the rule s3-bucket-discovered-public catches it via a
        # separate action (so operators can route it differently).
        if new_public:
            emit("s3.bucket.public",
                 reasons=new_public_reasons, region=e.get("region"))
        if new_encryption == "none":
            emit("s3.bucket.unencrypted", region=e.get("region"))
        if new_versioning in ("Suspended", "Disabled"):
            emit("s3.bucket.versioning_off", current=new_versioning, region=e.get("region"))
        return derived

    # Existing bucket — diff against prev.
    if prev.get("public") != new_public:
        if new_public:
            emit("s3.bucket.public",
                 reasons=new_public_reasons, region=e.get("region"))
        else:
            emit("s3.bucket.public_removed", region=e.get("region"))

    prev_enc = prev.get("encryption") or "none"
    if prev_enc != new_encryption:
        if new_encryption == "none":
            emit("s3.bucket.unencrypted",
                 prev_encryption=prev_enc, region=e.get("region"))
        elif prev_enc == "none":
            emit("s3.bucket.encryption_added",
                 encryption=new_encryption, region=e.get("region"))

    prev_versioning = prev.get("versioning") or "Disabled"
    if prev_versioning != new_versioning:
        if new_versioning == "Suspended" and prev_versioning == "Enabled":
            emit("s3.bucket.versioning_suspended", region=e.get("region"))
        elif new_versioning == "Enabled" and prev_versioning != "Enabled":
            emit("s3.bucket.versioning_enabled", region=e.get("region"))

    if prev.get("logging_target") and not logging_target:
        emit("s3.bucket.logging_disabled",
             prev_target=prev.get("logging_target"), region=e.get("region"))

    return derived


# ---------- s3.scan.completed -----------------------------------------------

def _project_scan_completed(event: Event) -> list[Event]:
    """Reconcile against the set of currently-known buckets. Any bucket BW
    tracks for this account that wasn't in this scan has vanished."""
    e = event.extra
    account = e.get("account")
    if not account:
        return []
    seen_in_this_scan = set(e.get("bucket_names") or [])
    when = event.event_time or datetime.now(timezone.utc)

    # Only reconcile buckets in this account (don't accidentally delete buckets
    # from other accounts the user might also scan).
    derived: list[Event] = []
    for tracked in storage.list_bucket_status():
        if tracked.get("account") != account:
            continue
        if tracked["bucket_name"] in seen_in_this_scan:
            continue
        # Disappeared. Emit + delete the row so it doesn't re-fire next scan.
        derived.append(_make_derived(
            event, tracked["bucket_name"], "s3.bucket.disappeared",
            {"region": tracked.get("region"), "account": account,
             "was_public": tracked.get("public"),
             "last_scan": tracked.get("last_scan").isoformat() if tracked.get("last_scan") else None},
            when,
        ))
        storage.delete_bucket_status(tracked["bucket_name"])
    return derived


def _make_derived(
    parent: Event, bucket_name: str, action: str,
    extras: dict[str, Any], when: datetime,
) -> Event:
    return Event(
        source=Source(module=_MODULE, vendor="aws",
                      account=parent.source.account,
                      region=extras.get("region") or parent.source.region,
                      transport=Transport.api),
        event_time=when,
        category=Category.storage,
        action=action,
        outcome=Outcome.success if action.endswith(("first_seen", "public_removed",
                                                     "encryption_added", "versioning_enabled"))
                else Outcome.failure,
        target=Target(id=bucket_name, type="aws.s3.bucket", name=bucket_name),
        extra={"bucket_name": bucket_name, **extras},
        raw={"derived_from": parent.action, "module": _MODULE},
    )


def _parse_iso(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
