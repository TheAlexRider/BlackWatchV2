"""AWS S3 drift scan — checks the current security posture of every bucket and
ships a snapshot report through the standard ingest pipeline.

Importable from both:
  * the in-app connector (`run_connector` dispatches to `poll()`)
  * the standalone `scripts/s3_bucket_inventory.py` (one-shot bootstrap that
    works without BlackWatch's container, using the operator's own AWS creds —
    runs `scan_account()` and POSTs the result to BW /ingest)

What it checks per bucket:
  * **Public access (the leak path)** — ACL grants, bucket policy with
    Principal=*, and the four PublicAccessBlock settings. A bucket is "public"
    if BPA isn't fully on AND (ACL grants to AllUsers/AuthenticatedUsers OR
    policy allows wildcard principal without scoping Condition).
  * **Encryption** — GetBucketEncryption; absence → 'none'.
  * **Versioning + MFA Delete** — GetBucketVersioning.
  * **Logging** — GetBucketLogging.
  * **Tags** — GetBucketTagging (non-fatal if missing).
  * **Policy** — raw doc, surfaced in UI for spot-check.

A failing call on any single bucket doesn't fail the whole scan — bucket-level
errors land in the per-bucket `extra.errors`. A region-wide failure for one
bucket just means that bucket's row is incomplete this cycle.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .. import pipeline
from .models import AwsS3DriftConfig


def _client(profile: str | None, region: str = "us-east-1"):
    import boto3
    session = boto3.session.Session(profile_name=profile or None, region_name=region)
    return session.client("s3")


def _bucket_region(s3_global, bucket: str) -> str:
    """`GetBucketLocation` returns None for us-east-1, 'EU' for eu-west-1, and
    proper region codes otherwise. Normalize to a region code."""
    try:
        loc = s3_global.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    except Exception:
        return "us-east-1"
    if loc is None or loc == "":
        return "us-east-1"
    if loc == "EU":
        return "eu-west-1"
    return loc


def _bucket_policy_is_public(doc_str: str) -> bool:
    """Same logic as the CloudTrail adapter — wildcard principal + no Condition
    on an Allow statement = public."""
    try:
        doc = json.loads(doc_str)
    except (ValueError, TypeError):
        return False
    statements = doc.get("Statement") or []
    if isinstance(statements, dict):
        statements = [statements]
    for s in statements:
        if not isinstance(s, dict) or s.get("Effect") != "Allow":
            continue
        principal = s.get("Principal")
        is_wildcard = (principal == "*" or (
            isinstance(principal, dict) and (
                principal.get("AWS") == "*"
                or (isinstance(principal.get("AWS"), list) and "*" in principal["AWS"])
            )))
        if is_wildcard and not s.get("Condition"):
            return True
    return False


def _acl_grants_public(acl_resp: dict[str, Any]) -> bool:
    """Inspect the Grants[] for AllUsers / AuthenticatedUsers grantee URIs."""
    for grant in acl_resp.get("Grants") or []:
        grantee = grant.get("Grantee") or {}
        uri = grantee.get("URI", "")
        if ("AllUsers" in uri) or ("AuthenticatedUsers" in uri):
            return True
    return False


def _scan_one_bucket(s3_global, bucket: dict[str, Any]) -> dict[str, Any]:
    """Build the per-bucket snapshot dict consumed by the adapter."""
    name = bucket["Name"]
    created = bucket.get("CreationDate")
    region = _bucket_region(s3_global, name)
    # Use a region-specific client for the per-bucket calls; some S3 APIs
    # require it (notably PublicAccessBlock).
    s3 = _client(profile=getattr(s3_global, "_blackwatch_profile", None), region=region)

    errors: list[str] = []
    public_reasons: list[str] = []

    # --- Public access block ----------------------------------------------------
    bpa = {
        "block_public_acls": False, "ignore_public_acls": False,
        "block_public_policy": False, "restrict_public_buckets": False,
    }
    try:
        bpa_resp = s3.get_public_access_block(Bucket=name)
        cfg = bpa_resp.get("PublicAccessBlockConfiguration") or {}
        bpa = {
            "block_public_acls": cfg.get("BlockPublicAcls", False),
            "ignore_public_acls": cfg.get("IgnorePublicAcls", False),
            "block_public_policy": cfg.get("BlockPublicPolicy", False),
            "restrict_public_buckets": cfg.get("RestrictPublicBuckets", False),
        }
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "NoSuchPublicAccessBlockConfiguration":
            errors.append(f"GetPublicAccessBlock: {code or str(exc)[:80]}")
        # If no BPA config exists, all four are effectively False — same as the default.
    bpa_full_on = all(bpa.values())
    if not bpa_full_on:
        public_reasons.append("bpa_off")

    # --- ACL --------------------------------------------------------------------
    try:
        acl_resp = s3.get_bucket_acl(Bucket=name)
        if _acl_grants_public(acl_resp):
            public_reasons.append("acl_grants_public")
    except Exception as exc:
        errors.append(f"GetBucketAcl: {str(exc)[:80]}")

    # --- Policy -----------------------------------------------------------------
    policy_doc: str | None = None
    try:
        pol_resp = s3.get_bucket_policy(Bucket=name)
        policy_doc = pol_resp.get("Policy")
        if policy_doc and _bucket_policy_is_public(policy_doc):
            public_reasons.append("policy_allows_public")
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "NoSuchBucketPolicy":
            errors.append(f"GetBucketPolicy: {code or str(exc)[:80]}")

    # --- Encryption -------------------------------------------------------------
    encryption = "none"
    try:
        enc_resp = s3.get_bucket_encryption(Bucket=name)
        rules = (enc_resp.get("ServerSideEncryptionConfiguration") or {}).get("Rules") or []
        for r in rules:
            algo = (r.get("ApplyServerSideEncryptionByDefault") or {}).get("SSEAlgorithm")
            if algo:
                encryption = algo
                break
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "ServerSideEncryptionConfigurationNotFoundError":
            errors.append(f"GetBucketEncryption: {code or str(exc)[:80]}")

    # --- Versioning + MFA Delete ------------------------------------------------
    versioning = "Disabled"
    mfa_delete = False
    try:
        ver_resp = s3.get_bucket_versioning(Bucket=name)
        versioning = ver_resp.get("Status") or "Disabled"
        mfa_delete = (ver_resp.get("MFADelete") == "Enabled")
    except Exception as exc:
        errors.append(f"GetBucketVersioning: {str(exc)[:80]}")

    # --- Logging ----------------------------------------------------------------
    logging_block: dict[str, Any] = {"enabled": False}
    try:
        log_resp = s3.get_bucket_logging(Bucket=name)
        le = log_resp.get("LoggingEnabled") or {}
        if le:
            logging_block = {
                "enabled": True,
                "target_bucket": le.get("TargetBucket"),
                "target_prefix": le.get("TargetPrefix"),
            }
    except Exception as exc:
        errors.append(f"GetBucketLogging: {str(exc)[:80]}")

    # --- Tags (non-fatal) -------------------------------------------------------
    tags: dict[str, str] = {}
    try:
        tag_resp = s3.get_bucket_tagging(Bucket=name)
        for t in tag_resp.get("TagSet") or []:
            if t.get("Key"):
                tags[t["Key"]] = t.get("Value", "")
    except s3.exceptions.ClientError:
        pass  # NoSuchTagSet is normal

    # Final "public?" — needs (BPA off) AND (something grants public). BPA-full-on
    # neutralizes ACL + policy public grants regardless of what they contain.
    public = (not bpa_full_on) and any(
        r in ("acl_grants_public", "policy_allows_public") for r in public_reasons)

    return {
        "name": name,
        "region": region,
        "created_date": created.isoformat() if created else None,
        "public": public,
        "public_reasons": [r for r in public_reasons if r in (
            "acl_grants_public", "policy_allows_public")] if public else [],
        "encryption": encryption,
        "versioning": versioning,
        "mfa_delete": mfa_delete,
        "block_public_access": bpa,
        "logging": logging_block,
        "policy": policy_doc,
        "tags": tags,
        "errors": errors,
    }


def scan_account(profile: str | None = None) -> dict[str, Any]:
    """Run a full inventory scan. ListBuckets is GLOBAL — no need to iterate
    regions for that part. Per-bucket calls hit each bucket's home region."""
    # Stash the profile name on the global client so per-bucket clients pick it up.
    s3_global = _client(profile=profile, region="us-east-1")
    s3_global._blackwatch_profile = profile

    try:
        lb = s3_global.list_buckets()
    except Exception as exc:
        return {
            "kind": "s3_bucket_snapshot", "buckets": [],
            "scanned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scanner_version": "1.0",
            "account": None,
            "scan_complete": False,
            "error": f"ListBuckets: {str(exc)[:160]}",
        }

    account = (lb.get("Owner") or {}).get("ID")
    bucket_dicts: list[dict[str, Any]] = []
    for b in lb.get("Buckets") or []:
        try:
            bucket_dicts.append(_scan_one_bucket(s3_global, b))
        except Exception as exc:
            bucket_dicts.append({
                "name": b.get("Name"), "region": None,
                "public": False, "encryption": "unknown",
                "versioning": "unknown", "errors": [str(exc)[:160]],
            })

    return {
        "kind": "s3_bucket_snapshot",
        "scanned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scanner_version": "1.0",
        "account": account,
        "buckets": bucket_dicts,
        "scan_complete": True,
    }


def poll(cfg: AwsS3DriftConfig) -> dict[str, Any]:
    """Connector entry — called by the scheduler. Builds the snapshot and pipes
    it through the standard ingest pipeline as if it had been POSTed externally."""
    report = scan_account(profile=cfg.aws_profile)
    stats = pipeline.ingest_payload("aws.s3", report, transport="poll")
    return {
        "ingested": stats.get("ingested", 0),
        "buckets": len(report.get("buckets") or []),
        "scan_complete": report.get("scan_complete", True),
    }
