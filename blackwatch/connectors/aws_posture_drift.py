"""AWS posture drift scan — Phase 2a checks.

Looks at the *current state* of AWS resources and emits findings for posture
problems that exist right now (not just things that changed recently).
Complements the CloudTrail-driven detections in aws_cloudtrail / rules:
CloudTrail catches change events; this catches "we already had this bad."

Phase 2a checks (Tier 1, build-now):
  * sg_public_ingress    — Security groups with ingress from 0.0.0.0/0
  * ebs_encryption       — EBS volumes without encryption at rest
  * ebs_snapshot_public  — EBS snapshots shared with `all`
  * ec2_imdsv2           — Running EC2 instances with HttpTokens != required

Each check returns one finding per resource that fails. Findings flow through
the aws.posture adapter → projection → posture_findings table. The projection
emits aws.posture.finding.new on first sight, aws.posture.finding.resolved
when a finding disappears (driven by aws.posture.scan.completed reconciliation).

All checks are read-only. The drift_config IAM policy this needs is in
deploy/aws-posture/blackwatch-aws-posture-policy.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .. import pipeline
from .models import AwsPostureDriftConfig


# Same risky-ports list the CloudTrail adapter uses for change-event detection.
# Kept duplicated rather than imported to keep modules independent.
_RISKY_PORTS = {
    22, 23, 25, 587, 465,
    139, 445, 389, 636,
    1433, 1521, 2049, 2375, 2376,
    3306, 3389, 5432, 5900, 5901,
    6379, 8086, 9200, 9300, 11211,
    27017, 27018,
}


def _session(profile: str | None, region: str = "us-east-1"):
    import boto3
    return boto3.session.Session(profile_name=profile or None, region_name=region)


def _account_id(session) -> str | None:
    try:
        return session.client("sts").get_caller_identity().get("Account")
    except Exception:
        return None


def _enabled_regions(session) -> list[str]:
    ec2 = session.client("ec2", region_name="us-east-1")
    try:
        return sorted(r["RegionName"]
                      for r in ec2.describe_regions(AllRegions=False).get("Regions") or [])
    except Exception:
        # Sensible fallback if describe-regions isn't permitted on this account.
        return ["us-east-1", "us-west-1", "us-west-2"]


# ---------- Security groups: public ingress ---------------------------------

def _check_sg_public_ingress(session, region: str) -> list[dict]:
    """One finding per SG, taking the worst issue (all-traffic > risky-port >
    non-web). Public 80/443 is treated as expected (web traffic). Anything
    else open to 0.0.0.0/0 or ::/0 is at minimum 'high'."""
    ec2 = session.client("ec2", region_name=region)
    out: list[dict] = []
    paginator = ec2.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for sg in page.get("SecurityGroups") or []:
            sg_id = sg["GroupId"]
            has_all_traffic = False
            risky_ports: set[int] = set()
            non_web_ports: set[int] = set()
            public_cidrs: set[str] = set()
            for perm in sg.get("IpPermissions") or []:
                cidrs = [r.get("CidrIp") for r in perm.get("IpRanges") or [] if r.get("CidrIp")]
                cidrs += [r.get("CidrIpv6") for r in perm.get("Ipv6Ranges") or [] if r.get("CidrIpv6")]
                public = [c for c in cidrs if c in ("0.0.0.0/0", "::/0")]
                if not public:
                    continue
                public_cidrs.update(public)
                proto = perm.get("IpProtocol")
                fp, tp = perm.get("FromPort"), perm.get("ToPort")
                if proto in ("-1", -1):
                    has_all_traffic = True
                    continue
                if fp is None:
                    continue  # protocols without ports (ICMP some shapes); skip
                if tp is None:
                    tp = fp
                if fp == 0 and tp >= 1024:
                    has_all_traffic = True
                    continue
                for p in range(fp, tp + 1):
                    if p in _RISKY_PORTS:
                        risky_ports.add(p)
                    elif p not in (80, 443):
                        non_web_ports.add(p)

            # Take only the worst single finding per SG.
            evidence_base = {
                "vpc_id": sg.get("VpcId"),
                "name": sg.get("GroupName"),
                "description": (sg.get("Description") or "")[:120],
                "cidrs": sorted(public_cidrs),
            }
            if has_all_traffic:
                out.append({
                    "resource_id": sg_id, "resource_type": "sg",
                    "finding_type": "public_ingress_all_traffic",
                    "severity": "critical", "region": region,
                    "evidence": {**evidence_base, "scope": "all protocols / ports"},
                })
            elif risky_ports:
                out.append({
                    "resource_id": sg_id, "resource_type": "sg",
                    "finding_type": "public_ingress_risky_port",
                    "severity": "critical", "region": region,
                    "evidence": {**evidence_base, "risky_ports": sorted(risky_ports)[:10]},
                })
            elif non_web_ports:
                out.append({
                    "resource_id": sg_id, "resource_type": "sg",
                    "finding_type": "public_ingress_non_web",
                    "severity": "high", "region": region,
                    "evidence": {**evidence_base, "non_web_ports": sorted(non_web_ports)[:10]},
                })
    return out


# ---------- EBS volumes: encryption -----------------------------------------

def _check_ebs_encryption(session, region: str) -> list[dict]:
    ec2 = session.client("ec2", region_name=region)
    out: list[dict] = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate():
        for vol in page.get("Volumes") or []:
            if vol.get("Encrypted"):
                continue
            attached = [a.get("InstanceId") for a in vol.get("Attachments") or []
                        if a.get("InstanceId")]
            out.append({
                "resource_id": vol["VolumeId"], "resource_type": "ebs_volume",
                "finding_type": "unencrypted",
                "severity": "high", "region": region,
                "evidence": {
                    "size_gb": vol.get("Size"),
                    "state": vol.get("State"),
                    "volume_type": vol.get("VolumeType"),
                    "attached_to": attached,
                    "tags": {t["Key"]: t["Value"] for t in vol.get("Tags") or []},
                },
            })
    return out


# ---------- EBS snapshots: publicly shared ----------------------------------

def _check_ebs_snapshot_public(session, region: str) -> list[dict]:
    """Find OUR own snapshots with createVolumePermission=all. That means
    anyone in any AWS account can restore the snapshot — direct exfil path."""
    ec2 = session.client("ec2", region_name=region)
    out: list[dict] = []
    paginator = ec2.get_paginator("describe_snapshots")
    for page in paginator.paginate(OwnerIds=["self"]):
        for snap in page.get("Snapshots") or []:
            try:
                attr = ec2.describe_snapshot_attribute(
                    SnapshotId=snap["SnapshotId"],
                    Attribute="createVolumePermission",
                )
            except Exception:
                continue
            is_public = any(
                (p.get("Group") == "all") for p in attr.get("CreateVolumePermissions") or []
            )
            if not is_public:
                continue
            start_time = snap.get("StartTime")
            out.append({
                "resource_id": snap["SnapshotId"], "resource_type": "ebs_snapshot",
                "finding_type": "public",
                "severity": "critical", "region": region,
                "evidence": {
                    "volume_id": snap.get("VolumeId"),
                    "size_gb": snap.get("VolumeSize"),
                    "description": (snap.get("Description") or "")[:120],
                    "start_time": start_time.isoformat() if hasattr(start_time, "isoformat") else None,
                },
            })
    return out


# ---------- EC2 instances: IMDSv2 required? ---------------------------------

def _check_ec2_imdsv2(session, region: str) -> list[dict]:
    """Running instances with HttpTokens != 'required' (i.e. IMDSv1 still
    works). The single biggest EC2 instance-credential-theft vector that
    exists; closing it costs nothing."""
    ec2 = session.client("ec2", region_name=region)
    out: list[dict] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for res in page.get("Reservations") or []:
            for inst in res.get("Instances") or []:
                if (inst.get("State") or {}).get("Name") != "running":
                    continue
                meta = inst.get("MetadataOptions") or {}
                if meta.get("HttpTokens") == "required":
                    continue
                out.append({
                    "resource_id": inst["InstanceId"], "resource_type": "ec2_instance",
                    "finding_type": "imdsv1_enabled",
                    "severity": "high", "region": region,
                    "evidence": {
                        "http_tokens": meta.get("HttpTokens"),
                        "http_endpoint": meta.get("HttpEndpoint"),
                        "instance_type": inst.get("InstanceType"),
                        "tags": {t["Key"]: t["Value"] for t in inst.get("Tags") or []},
                        "iam_instance_profile": (inst.get("IamInstanceProfile") or {}).get("Arn"),
                    },
                })
    return out


# ---------- Driver ----------------------------------------------------------

def scan_account(cfg: AwsPostureDriftConfig) -> dict[str, Any]:
    session = _session(cfg.aws_profile)
    account = _account_id(session)
    regions = cfg.regions or _enabled_regions(session)

    checks_run: list[str] = []
    findings: list[dict] = []
    errors: list[str] = []

    # --- Account-global checks (IAM + CloudTrail) ---
    # IAM is a global service; CloudTrail multi-region trails appear in every
    # region's listing, so a single us-east-1 call covers the account.
    if cfg.check_iam_user_no_mfa:
        try:
            findings.extend(_check_iam_user_no_mfa(session))
            checks_run.append("iam_user_no_mfa")
        except Exception as exc:
            errors.append(f"iam_user_no_mfa:{str(exc)[:120]}")
    if cfg.check_iam_key_age:
        try:
            findings.extend(_check_iam_access_key_age(session, cfg.iam_key_max_age_days))
            checks_run.append("iam_key_age")
        except Exception as exc:
            errors.append(f"iam_key_age:{str(exc)[:120]}")
    if cfg.check_iam_key_unused:
        try:
            findings.extend(_check_iam_access_key_unused(session, cfg.iam_key_unused_threshold_days))
            checks_run.append("iam_key_unused")
        except Exception as exc:
            errors.append(f"iam_key_unused:{str(exc)[:120]}")
    if cfg.check_iam_role_wildcard_trust:
        try:
            findings.extend(_check_iam_role_wildcard_trust(session))
            checks_run.append("iam_role_wildcard_trust")
        except Exception as exc:
            errors.append(f"iam_role_wildcard_trust:{str(exc)[:120]}")
    if cfg.check_cloudtrail_validation:
        try:
            findings.extend(_check_cloudtrail_validation(session))
            checks_run.append("cloudtrail_validation")
        except Exception as exc:
            errors.append(f"cloudtrail_validation:{str(exc)[:120]}")

    # --- Per-region checks ---
    for region in regions:
        if cfg.check_sg_public_ingress:
            try:
                findings.extend(_check_sg_public_ingress(session, region))
            except Exception as exc:
                errors.append(f"{region}:sg:{str(exc)[:120]}")
        if cfg.check_ebs_encryption:
            try:
                findings.extend(_check_ebs_encryption(session, region))
            except Exception as exc:
                errors.append(f"{region}:ebs_enc:{str(exc)[:120]}")
        if cfg.check_ebs_snapshot_public:
            try:
                findings.extend(_check_ebs_snapshot_public(session, region))
            except Exception as exc:
                errors.append(f"{region}:ebs_snap:{str(exc)[:120]}")
        if cfg.check_ec2_imdsv2:
            try:
                findings.extend(_check_ec2_imdsv2(session, region))
            except Exception as exc:
                errors.append(f"{region}:imds:{str(exc)[:120]}")
        if cfg.check_kms_rotation:
            try:
                findings.extend(_check_kms_rotation(session, region))
            except Exception as exc:
                errors.append(f"{region}:kms_rotation:{str(exc)[:120]}")
        if cfg.check_kms_policy_wildcard:
            try:
                findings.extend(_check_kms_key_policy_wildcard(session, region))
            except Exception as exc:
                errors.append(f"{region}:kms_policy:{str(exc)[:120]}")
        if cfg.check_ami_public:
            try:
                findings.extend(_check_ami_public(session, region))
            except Exception as exc:
                errors.append(f"{region}:ami:{str(exc)[:120]}")
        if cfg.check_rds:
            try:
                findings.extend(_check_rds_findings(session, region))
                # Inventory events also emitted from here — they don't go
                # into the findings list (those are for /aws-posture); they
                # go straight through pipeline.process_event so /rds shows
                # every DB the account owns, not just the ones with issues.
                _emit_rds_inventory(session, region, account)
            except Exception as exc:
                errors.append(f"{region}:rds:{str(exc)[:120]}")

    if cfg.check_sg_public_ingress:        checks_run.append("sg_public_ingress")
    if cfg.check_ebs_encryption:           checks_run.append("ebs_encryption")
    if cfg.check_ebs_snapshot_public:      checks_run.append("ebs_snapshot_public")
    if cfg.check_ec2_imdsv2:               checks_run.append("ec2_imdsv2")
    if cfg.check_kms_rotation:             checks_run.append("kms_rotation")
    if cfg.check_kms_policy_wildcard:      checks_run.append("kms_policy_wildcard")
    if cfg.check_ami_public:               checks_run.append("ami_public")
    if cfg.check_rds:                      checks_run.append("rds")

    # A scan with ANY region/check erroring is treated as incomplete — better
    # to skip the resolved-reconciliation than wrongly mark live findings
    # resolved because a transient AWS API blip dropped some of them from the
    # report.
    scan_complete = not errors

    return {
        "kind": "aws_posture_report",
        "scanned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scanner_version": "1.1",  # Phase 2b additions
        "account": account,
        "checks_run": checks_run,
        "regions_scanned": regions,
        "findings": findings,
        "errors": errors,
        "scan_complete": scan_complete,
    }


def poll(cfg: AwsPostureDriftConfig) -> dict[str, Any]:
    report = scan_account(cfg)
    stats = pipeline.ingest_payload("aws.posture", report, transport="poll")
    return {
        "ingested": stats.get("ingested", 0),
        "findings": len(report.get("findings") or []),
        "scan_complete": report.get("scan_complete", True),
        "errors": len(report.get("errors") or []),
    }


# ---------- Phase 2b: IAM, KMS, CloudTrail hygiene --------------------------
#
# IAM checks are GLOBAL (one call per account, no region iteration).
# KMS checks are per-region (CMKs are regional resources).
# CloudTrail check is account-level — multi-region trails appear in every
# region's DescribeTrails listing, so one call to us-east-1 covers everything.


def _policy_doc_has_wildcard_principal(doc_str: Any) -> bool:
    """Returns True if the policy doc has Allow + Principal=* without a
    scoping Condition. Used by the KMS-policy and IAM-role-trust checks.

    Important nuance: KMS default policies always include
    `{"AWS": "arn:aws:iam::ACCOUNT:root"}` as a Principal — that's NOT
    wildcard. We're explicitly looking for the literal `"*"` or
    `{"AWS": "*"}` shapes."""
    if not isinstance(doc_str, str):
        # IAM ListRoles returns the trust policy as a parsed dict, not a string.
        if isinstance(doc_str, dict):
            doc = doc_str
        else:
            return False
    else:
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
        p = s.get("Principal")
        is_wild = p == "*" or (isinstance(p, dict) and (
            p.get("AWS") == "*"
            or (isinstance(p.get("AWS"), list) and "*" in p["AWS"])
        ))
        if is_wild and not s.get("Condition"):
            return True
    return False


def _check_iam_user_no_mfa(session) -> list[dict]:
    """IAM users with a console login profile but no MFA device. Service-style
    users (no console password) are not in scope — they don't use MFA anyway.
    Catches "person left, account not deleted, no MFA" + lazy admin onboarding."""
    iam = session.client("iam")
    out: list[dict] = []
    paginator = iam.get_paginator("list_users")
    for page in paginator.paginate():
        for user in page.get("Users") or []:
            name = user["UserName"]
            try:
                iam.get_login_profile(UserName=name)
            except iam.exceptions.NoSuchEntityException:
                continue  # no console password = nothing to MFA-protect
            except Exception:
                continue
            try:
                mfa_resp = iam.list_mfa_devices(UserName=name)
                if mfa_resp.get("MFADevices"):
                    continue
            except Exception:
                continue
            created = user.get("CreateDate")
            out.append({
                "resource_id": f"iam:user/{name}",
                "resource_type": "iam_user",
                "finding_type": "no_mfa",
                "severity": "high",
                "region": None,
                "evidence": {
                    "user_name": name,
                    "arn": user.get("Arn"),
                    "created_date": created.isoformat() if created else None,
                },
            })
    return out


def _check_iam_access_key_age(session, max_age_days: int) -> list[dict]:
    """Active access keys older than the rotation threshold (default 90 days).
    Severity scales: 90–180d = medium, >180d = high."""
    iam = session.client("iam")
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    paginator = iam.get_paginator("list_users")
    for page in paginator.paginate():
        for user in page.get("Users") or []:
            name = user["UserName"]
            try:
                keys = iam.list_access_keys(UserName=name).get("AccessKeyMetadata") or []
            except Exception:
                continue
            for k in keys:
                if k.get("Status") != "Active":
                    continue
                created = k.get("CreateDate")
                if not created:
                    continue
                age_days = (now - created).days
                if age_days <= max_age_days:
                    continue
                out.append({
                    "resource_id": f"iam:access-key/{k['AccessKeyId']}",
                    "resource_type": "iam_access_key",
                    "finding_type": "older_than_threshold",
                    "severity": "high" if age_days > 180 else "medium",
                    "region": None,
                    "evidence": {
                        "user_name": name,
                        "access_key_id": k["AccessKeyId"],
                        "age_days": age_days,
                        "created_date": created.isoformat(),
                        "threshold_days": max_age_days,
                    },
                })
    return out


def _check_iam_access_key_unused(session, unused_days: int) -> list[dict]:
    """Active access keys not used in N days. Catches "we issued this for a
    project, forgot to revoke." Different finding from age-based — a recently-
    rotated key that's also unused is a different signal than an old key."""
    iam = session.client("iam")
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    paginator = iam.get_paginator("list_users")
    for page in paginator.paginate():
        for user in page.get("Users") or []:
            name = user["UserName"]
            try:
                keys = iam.list_access_keys(UserName=name).get("AccessKeyMetadata") or []
            except Exception:
                continue
            for k in keys:
                if k.get("Status") != "Active":
                    continue
                created = k.get("CreateDate")
                try:
                    lu = iam.get_access_key_last_used(AccessKeyId=k["AccessKeyId"])
                except Exception:
                    continue
                last_used = (lu.get("AccessKeyLastUsed") or {}).get("LastUsedDate")
                if last_used is None:
                    # Never used. Give it a grace period — recently-created
                    # keys for someone setting up a new service get ignored.
                    age = (now - created).days if created else 0
                    if age <= 30:
                        continue
                    out.append({
                        "resource_id": f"iam:access-key/{k['AccessKeyId']}",
                        "resource_type": "iam_access_key",
                        "finding_type": "never_used",
                        "severity": "medium",
                        "region": None,
                        "evidence": {
                            "user_name": name,
                            "access_key_id": k["AccessKeyId"],
                            "age_days": age,
                        },
                    })
                    continue
                days_since = (now - last_used).days
                if days_since > unused_days:
                    out.append({
                        "resource_id": f"iam:access-key/{k['AccessKeyId']}",
                        "resource_type": "iam_access_key",
                        "finding_type": "unused_recently",
                        "severity": "medium",
                        "region": None,
                        "evidence": {
                            "user_name": name,
                            "access_key_id": k["AccessKeyId"],
                            "days_since_use": days_since,
                            "last_used": last_used.isoformat(),
                            "threshold_days": unused_days,
                        },
                    })
    return out


def _check_iam_role_wildcard_trust(session) -> list[dict]:
    """IAM roles whose assume-role policy allows Principal=* with no Condition.
    Anyone who knows the role ARN can assume it = total role compromise.
    Service-linked roles (with their canonical AWS-service principals) are
    filtered out automatically since their Principal is the service, not '*'."""
    iam = session.client("iam")
    out: list[dict] = []
    paginator = iam.get_paginator("list_roles")
    for page in paginator.paginate():
        for role in page.get("Roles") or []:
            doc = role.get("AssumeRolePolicyDocument")
            if not _policy_doc_has_wildcard_principal(doc):
                continue
            created = role.get("CreateDate")
            out.append({
                "resource_id": f"iam:role/{role['RoleName']}",
                "resource_type": "iam_role",
                "finding_type": "trust_policy_wildcard",
                "severity": "critical",
                "region": None,
                "evidence": {
                    "role_name": role["RoleName"],
                    "arn": role.get("Arn"),
                    "created_date": created.isoformat() if created else None,
                    "description": (role.get("Description") or "")[:120],
                },
            })
    return out


def _check_kms_rotation(session, region: str) -> list[dict]:
    """Customer-managed CMKs without automatic rotation enabled. AWS-managed
    keys handle their own rotation; external/HSM key material can't rotate via
    AWS. We only flag CUSTOMER-managed, Enabled, AWS_KMS-origin keys."""
    kms = session.client("kms", region_name=region)
    out: list[dict] = []
    paginator = kms.get_paginator("list_keys")
    for page in paginator.paginate():
        for key in page.get("Keys") or []:
            key_id = key["KeyId"]
            try:
                meta = kms.describe_key(KeyId=key_id).get("KeyMetadata") or {}
            except Exception:
                continue
            if (meta.get("KeyManager") != "CUSTOMER"
                    or meta.get("KeyState") != "Enabled"
                    or (meta.get("Origin") and meta["Origin"] != "AWS_KMS")):
                continue
            try:
                rotation = kms.get_key_rotation_status(KeyId=key_id)
            except Exception:
                continue
            if rotation.get("KeyRotationEnabled"):
                continue
            created = meta.get("CreationDate")
            out.append({
                "resource_id": f"kms:key/{key_id}",
                "resource_type": "kms_key",
                "finding_type": "rotation_disabled",
                "severity": "medium",
                "region": region,
                "evidence": {
                    "key_id": key_id,
                    "arn": meta.get("Arn"),
                    "description": (meta.get("Description") or "")[:120],
                    "created_date": created.isoformat() if created else None,
                },
            })
    return out


def _check_kms_key_policy_wildcard(session, region: str) -> list[dict]:
    """CMKs whose key policy allows wildcard principal without a Condition.
    Different from `_check_kms_rotation`: this catches the standing-state
    misconfig that means anyone (or any account) can use the key right now."""
    kms = session.client("kms", region_name=region)
    out: list[dict] = []
    paginator = kms.get_paginator("list_keys")
    for page in paginator.paginate():
        for key in page.get("Keys") or []:
            key_id = key["KeyId"]
            try:
                meta = kms.describe_key(KeyId=key_id).get("KeyMetadata") or {}
            except Exception:
                continue
            if (meta.get("KeyManager") != "CUSTOMER"
                    or meta.get("KeyState") != "Enabled"):
                continue
            try:
                policy = kms.get_key_policy(KeyId=key_id, PolicyName="default").get("Policy")
            except Exception:
                continue
            if not _policy_doc_has_wildcard_principal(policy):
                continue
            out.append({
                "resource_id": f"kms:key/{key_id}",
                "resource_type": "kms_key",
                "finding_type": "policy_wildcard_principal",
                "severity": "critical",
                "region": region,
                "evidence": {
                    "key_id": key_id,
                    "arn": meta.get("Arn"),
                    "description": (meta.get("Description") or "")[:120],
                },
            })
    return out


def _check_cloudtrail_validation(session) -> list[dict]:
    """Account-level CloudTrail posture. Three sub-findings can fire per scan:
      - no_multi_region_trail: no trail is multi-region+logging (single biggest
        audit gap an AWS account can have)
      - not_logging: a trail exists but isn't currently logging
      - log_file_validation_disabled: trail is logging but without integrity
        validation enabled (forensic-quality gap)
    `DescribeTrails` in us-east-1 returns all trails account-wide because
    multi-region trails appear in every region's listing by default."""
    ct = session.client("cloudtrail", region_name="us-east-1")
    out: list[dict] = []
    try:
        trails = ct.describe_trails().get("trailList") or []
    except Exception:
        return out
    any_multi_logging = False
    for t in trails:
        name = t.get("Name") or "?"
        arn = t.get("TrailARN") or name
        is_multi = bool(t.get("IsMultiRegionTrail"))
        has_validation = bool(t.get("LogFileValidationEnabled"))
        home_region = t.get("HomeRegion") or "us-east-1"
        try:
            status = ct.get_trail_status(Name=arn)
            is_logging = bool(status.get("IsLogging"))
        except Exception:
            is_logging = False
        if is_multi and is_logging:
            any_multi_logging = True
        if not is_logging:
            out.append({
                "resource_id": arn,
                "resource_type": "cloudtrail",
                "finding_type": "not_logging",
                "severity": "high",
                "region": home_region,
                "evidence": {"trail_name": name, "is_multi_region": is_multi},
            })
        elif not has_validation:
            out.append({
                "resource_id": arn,
                "resource_type": "cloudtrail",
                "finding_type": "log_file_validation_disabled",
                "severity": "medium",
                "region": home_region,
                "evidence": {"trail_name": name, "is_multi_region": is_multi},
            })
    if not any_multi_logging:
        # Account-level finding: NO multi-region trail is actively logging.
        out.append({
            "resource_id": "cloudtrail:account",
            "resource_type": "cloudtrail",
            "finding_type": "no_multi_region_trail",
            "severity": "high",
            "region": None,
            "evidence": {"trail_count": len(trails)},
        })
    return out


# ---------- RDS: posture findings + per-instance inventory events ----------
#
# Two outputs from one scan:
#   * findings: dropped into the report so /aws-posture lights up for bad-state
#     instances (publicly accessible, no backups, etc.).
#   * inventory events: one rds.instance.state event PER instance, emitted
#     directly through the pipeline so the /rds page can show every DB the
#     account owns — not just the ones with current findings.
#
# The inventory events use a deterministic event_id keyed on (account,
# instance, scan-day) so re-runs within the same day dedup at insert (no
# table-bloat) while still updating freshness for the /rds view.


_RDS_SCAN_ENGINES_CONSIDERED = ("postgres", "mysql", "mariadb", "oracle", "sqlserver")


def _check_rds_findings(session, region: str) -> list[dict]:
    """Per-instance posture findings. Mirrors the rds_* flags the CloudTrail
    adapter sets — same names, so /rds shows the same chip in both the
    change-event row and the posture-finding card."""
    rds = session.client("rds", region_name=region)
    out: list[dict] = []
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for inst in page.get("DBInstances") or []:
            ident = inst.get("DBInstanceIdentifier")
            if not ident:
                continue
            evidence_base = {
                "instance_id": ident,
                "engine": inst.get("Engine"),
                "engine_version": inst.get("EngineVersion"),
                "instance_class": inst.get("DBInstanceClass"),
                "endpoint": (inst.get("Endpoint") or {}).get("Address"),
            }
            if inst.get("PubliclyAccessible"):
                out.append({
                    "resource_id": f"rds:db/{ident}",
                    "resource_type": "rds_instance",
                    "finding_type": "publicly_accessible",
                    "severity": "critical",
                    "region": region,
                    "evidence": evidence_base,
                })
            if not inst.get("StorageEncrypted"):
                out.append({
                    "resource_id": f"rds:db/{ident}",
                    "resource_type": "rds_instance",
                    "finding_type": "unencrypted_storage",
                    "severity": "high",
                    "region": region,
                    "evidence": evidence_base,
                })
            if (inst.get("BackupRetentionPeriod") or 0) == 0:
                out.append({
                    "resource_id": f"rds:db/{ident}",
                    "resource_type": "rds_instance",
                    "finding_type": "no_backups",
                    "severity": "high",
                    "region": region,
                    "evidence": evidence_base,
                })
            if not inst.get("DeletionProtection"):
                out.append({
                    "resource_id": f"rds:db/{ident}",
                    "resource_type": "rds_instance",
                    "finding_type": "no_deletion_protection",
                    "severity": "medium",
                    "region": region,
                    "evidence": evidence_base,
                })
            if not inst.get("IAMDatabaseAuthenticationEnabled"):
                out.append({
                    "resource_id": f"rds:db/{ident}",
                    "resource_type": "rds_instance",
                    "finding_type": "iam_auth_disabled",
                    "severity": "medium",
                    "region": region,
                    "evidence": evidence_base,
                })
    return out


def _emit_rds_inventory(session, region: str, account: str | None) -> int:
    """One rds.instance.state event per DB found in this region. The /rds
    page shows ANY instance that has at least one event with action prefix
    rds.* — so this is what makes the page populate even for instances that
    have never had a CloudTrail change event.

    Event id is deterministic on (account, instance, day) so an hourly
    scanner doesn't spam — one row per instance per day at most. The latest
    row per instance wins on the page."""
    from datetime import datetime as _dt, timezone as _tz
    import uuid as _uuid
    from .. import pipeline as _pipeline
    from ..event import (
        Actor as _Actor,
        Category as _Category,
        Event as _Event,
        Outcome as _Outcome,
        Source as _Source,
        Target as _Target,
        Transport as _Transport,
    )

    rds = session.client("rds", region_name=region)
    today = _dt.now(_tz.utc).strftime("%Y%m%d")
    emitted = 0
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for inst in page.get("DBInstances") or []:
            ident = inst.get("DBInstanceIdentifier")
            if not ident:
                continue

            # Mirror the rds_* extras the CloudTrail adapter writes. Names
            # must match exactly so the /rds page's flag chips render the
            # same way whether the source is a state poll or a change event.
            extras: dict[str, Any] = {
                "source": "drift-scan",
                "engine": inst.get("Engine"),
                "engine_version": inst.get("EngineVersion"),
                "instance_class": inst.get("DBInstanceClass"),
                "endpoint": (inst.get("Endpoint") or {}).get("Address"),
                "endpoint_port": (inst.get("Endpoint") or {}).get("Port"),
                "az": inst.get("AvailabilityZone"),
                "multi_az": inst.get("MultiAZ"),
                "backup_retention_days": inst.get("BackupRetentionPeriod"),
                "storage_encrypted": inst.get("StorageEncrypted"),
                "deletion_protection": inst.get("DeletionProtection"),
                "iam_auth_enabled": inst.get("IAMDatabaseAuthenticationEnabled"),
                "publicly_accessible": inst.get("PubliclyAccessible"),
                "status": inst.get("DBInstanceStatus"),
            }
            if inst.get("PubliclyAccessible"):
                extras["rds_publicly_accessible"] = True
            if not inst.get("StorageEncrypted"):
                extras["rds_unencrypted_at_creation"] = True
            if (inst.get("BackupRetentionPeriod") or 0) == 0:
                extras["rds_backups_disabled"] = True
            if not inst.get("DeletionProtection"):
                extras["rds_deletion_protection_off"] = True
            if not inst.get("IAMDatabaseAuthenticationEnabled"):
                extras["rds_iam_auth_disabled"] = True

            event_id = str(_uuid.uuid5(
                _uuid.NAMESPACE_URL,
                f"rds-state:{account or '-'}:{region}:{ident}:{today}",
            ))
            event = _Event(
                event_id=event_id,
                source=_Source(
                    module="aws.cloudtrail",  # same module so /rds query catches it
                    vendor="aws",
                    account=account,
                    region=region,
                    transport=_Transport.poll,
                ),
                event_time=_dt.now(_tz.utc),
                category=_Category.storage,
                action="rds.instance.state",
                outcome=_Outcome.success,
                actor=_Actor(principal="aws_posture_drift", source_ip=None),
                target=_Target(id=ident, type="aws.rds", name=ident),
                tags=["rds", "inventory"],
                extra=extras,
                raw={"engine": inst.get("Engine"), "instance_id": ident},
            )
            _pipeline.process_event(event)
            emitted += 1
    return emitted


def _check_ami_public(session, region: str) -> list[dict]:
    """Find AMIs YOU own that have launchPermission group 'all'. Sometimes
    intentional (open-source AMI release), but always worth knowing."""
    ec2 = session.client("ec2", region_name=region)
    out: list[dict] = []
    try:
        resp = ec2.describe_images(Owners=["self"])
    except Exception:
        return out
    for img in resp.get("Images") or []:
        # Need a second call to get launch permissions
        try:
            attr = ec2.describe_image_attribute(
                ImageId=img["ImageId"], Attribute="launchPermission",
            )
        except Exception:
            continue
        is_public = any(
            p.get("Group") == "all" for p in attr.get("LaunchPermissions") or []
        )
        if not is_public:
            continue
        out.append({
            "resource_id": img["ImageId"],
            "resource_type": "ami",
            "finding_type": "public",
            "severity": "high",
            "region": region,
            "evidence": {
                "name": img.get("Name"),
                "description": (img.get("Description") or "")[:120],
                "creation_date": img.get("CreationDate"),
            },
        })
    return out
