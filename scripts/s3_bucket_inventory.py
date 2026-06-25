#!/usr/bin/env python3
"""BlackWatch S3 bucket inventory — one-shot bootstrap.

Run this from your laptop or a jump box BEFORE setting up the in-app drift
connector. It enumerates every S3 bucket in the account using your local AWS
creds, reads the security posture of each, and either:
  (a) POSTs the result to BlackWatch /ingest (so the projection establishes
      the initial baseline + the buckets show up in /ui/buckets), or
  (b) saves the snapshot to a local JSON file if BW isn't reachable.

This is the SAME logic the in-app `aws_s3_drift` connector runs every hour;
this script just lets you do the first scan without going through the
container. After this initial bootstrap, the connector takes over for ongoing
drift detection.

Usage:

    # Push directly into BlackWatch (the normal path):
    BLACKWATCH_URL=http://localhost:8000 \\
    BLACKWATCH_TOKEN=<a token mapped to module=aws.s3 in BLACKWATCH_TOKENS> \\
    AWS_PROFILE=default \\
    python scripts/s3_bucket_inventory.py

    # Or just dump the snapshot to a file (no BW required):
    AWS_PROFILE=default python scripts/s3_bucket_inventory.py --out snapshot.json

The script is intentionally standalone (only boto3 + stdlib) so it can run on
any box with AWS credentials, including one without BlackWatch installed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone


# We deliberately do NOT import blackwatch.* — this script must be runnable
# without the BlackWatch package being installed. The scan logic is duplicated
# here for portability, kept narrow.

def _client(profile: str | None, region: str = "us-east-1"):
    import boto3
    return boto3.session.Session(
        profile_name=profile or None, region_name=region,
    ).client("s3")


def _bucket_region(s3_global, bucket: str) -> str:
    try:
        loc = s3_global.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    except Exception:
        return "us-east-1"
    if not loc:
        return "us-east-1"
    if loc == "EU":
        return "eu-west-1"
    return loc


def _policy_is_public(doc_str: str) -> bool:
    try:
        doc = json.loads(doc_str)
    except (ValueError, TypeError):
        return False
    stmts = doc.get("Statement") or []
    if isinstance(stmts, dict):
        stmts = [stmts]
    for s in stmts:
        if not isinstance(s, dict) or s.get("Effect") != "Allow":
            continue
        p = s.get("Principal")
        wildcard = (p == "*" or (
            isinstance(p, dict) and (
                p.get("AWS") == "*"
                or (isinstance(p.get("AWS"), list) and "*" in p["AWS"])
            )))
        if wildcard and not s.get("Condition"):
            return True
    return False


def _acl_grants_public(acl_resp) -> bool:
    for g in acl_resp.get("Grants") or []:
        uri = (g.get("Grantee") or {}).get("URI", "")
        if "AllUsers" in uri or "AuthenticatedUsers" in uri:
            return True
    return False


def _scan_one(s3_global, profile: str | None, bucket: dict) -> dict:
    name = bucket["Name"]
    region = _bucket_region(s3_global, name)
    s3 = _client(profile=profile, region=region)
    errors: list[str] = []
    reasons: list[str] = []

    bpa = {"block_public_acls": False, "ignore_public_acls": False,
           "block_public_policy": False, "restrict_public_buckets": False}
    try:
        cfg = (s3.get_public_access_block(Bucket=name)
               .get("PublicAccessBlockConfiguration") or {})
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
    bpa_full = all(bpa.values())

    try:
        if _acl_grants_public(s3.get_bucket_acl(Bucket=name)):
            reasons.append("acl_grants_public")
    except Exception as exc:
        errors.append(f"GetBucketAcl: {str(exc)[:80]}")

    policy_doc = None
    try:
        policy_doc = s3.get_bucket_policy(Bucket=name).get("Policy")
        if policy_doc and _policy_is_public(policy_doc):
            reasons.append("policy_allows_public")
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "NoSuchBucketPolicy":
            errors.append(f"GetBucketPolicy: {code or str(exc)[:80]}")

    encryption = "none"
    try:
        rules = ((s3.get_bucket_encryption(Bucket=name)
                  .get("ServerSideEncryptionConfiguration") or {})
                 .get("Rules") or [])
        for r in rules:
            algo = (r.get("ApplyServerSideEncryptionByDefault") or {}).get("SSEAlgorithm")
            if algo:
                encryption = algo
                break
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "ServerSideEncryptionConfigurationNotFoundError":
            errors.append(f"GetBucketEncryption: {code or str(exc)[:80]}")

    versioning, mfa_delete = "Disabled", False
    try:
        v = s3.get_bucket_versioning(Bucket=name)
        versioning = v.get("Status") or "Disabled"
        mfa_delete = (v.get("MFADelete") == "Enabled")
    except Exception as exc:
        errors.append(f"GetBucketVersioning: {str(exc)[:80]}")

    logging = {"enabled": False}
    try:
        le = s3.get_bucket_logging(Bucket=name).get("LoggingEnabled") or {}
        if le:
            logging = {"enabled": True,
                       "target_bucket": le.get("TargetBucket"),
                       "target_prefix": le.get("TargetPrefix")}
    except Exception as exc:
        errors.append(f"GetBucketLogging: {str(exc)[:80]}")

    tags: dict[str, str] = {}
    try:
        for t in s3.get_bucket_tagging(Bucket=name).get("TagSet") or []:
            if t.get("Key"):
                tags[t["Key"]] = t.get("Value", "")
    except s3.exceptions.ClientError:
        pass

    public = (not bpa_full) and bool(reasons)
    return {
        "name": name,
        "region": region,
        "created_date": bucket.get("CreationDate").isoformat() if bucket.get("CreationDate") else None,
        "public": public,
        "public_reasons": reasons if public else [],
        "encryption": encryption,
        "versioning": versioning,
        "mfa_delete": mfa_delete,
        "block_public_access": bpa,
        "logging": logging,
        "policy": policy_doc,
        "tags": tags,
        "errors": errors,
    }


def scan_account(profile: str | None) -> dict:
    s3 = _client(profile=profile, region="us-east-1")
    try:
        lb = s3.list_buckets()
    except Exception as exc:
        return {
            "kind": "s3_bucket_snapshot", "buckets": [],
            "scanned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scanner_version": "1.0", "account": None,
            "scan_complete": False, "error": f"ListBuckets: {str(exc)[:200]}",
        }
    account = (lb.get("Owner") or {}).get("ID")
    bucket_dicts = []
    total = len(lb.get("Buckets") or [])
    for i, b in enumerate(lb.get("Buckets") or [], 1):
        name = b.get("Name", "?")
        print(f"  [{i}/{total}] scanning {name}…", file=sys.stderr)
        try:
            bucket_dicts.append(_scan_one(s3, profile, b))
        except Exception as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            bucket_dicts.append({"name": name, "errors": [str(exc)[:200]]})
    return {
        "kind": "s3_bucket_snapshot",
        "scanned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scanner_version": "1.0",
        "account": account,
        "buckets": bucket_dicts,
        "scan_complete": True,
    }


def post_to_blackwatch(url: str, token: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/ingest",
        method="POST", data=body,
        headers={"Content-Type": "application/json",
                 "X-BlackWatch-Token": token},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan all S3 buckets for security posture and send to BlackWatch.")
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"),
                    help="AWS profile name (default: $AWS_PROFILE or system default)")
    ap.add_argument("--url", default=os.environ.get("BLACKWATCH_URL"),
                    help="BlackWatch URL (default: $BLACKWATCH_URL)")
    ap.add_argument("--token", default=os.environ.get("BLACKWATCH_TOKEN"),
                    help="Bearer token (must be mapped to module=aws.s3 in BLACKWATCH_TOKENS)")
    ap.add_argument("--out", help="Save snapshot to file instead of POSTing")
    args = ap.parse_args()

    print(f"Scanning S3 inventory (profile={args.profile or 'default'})…", file=sys.stderr)
    report = scan_account(args.profile)
    print(f"Scan complete: {len(report.get('buckets') or [])} buckets, "
          f"account={report.get('account')}, scan_complete={report.get('scan_complete')}",
          file=sys.stderr)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Saved to {args.out}", file=sys.stderr)
        return

    if not (args.url and args.token):
        print("ERROR: need --url + --token (or BLACKWATCH_URL + BLACKWATCH_TOKEN) to POST. "
              "Use --out FILE to save to disk instead.", file=sys.stderr)
        sys.exit(2)

    try:
        result = post_to_blackwatch(args.url, args.token, report)
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(f"POST failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
