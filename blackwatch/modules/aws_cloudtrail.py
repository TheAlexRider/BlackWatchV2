"""AWS CloudTrail adapter.

Consumes a CloudTrail record (or the EventBridge "AWS API Call via CloudTrail"
envelope that wraps it in `detail`) and emits a normalized event. Pure
transform: maps eventName -> normalized action and extracts actor/target/
observables. The EventBridge rule does the high-value filtering upstream, so
most records map to a specific action; anything unmapped still flows through as
`aws.<service>.<eventname>` (category audit) so nothing is silently dropped.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor,
    ActorType,
    Category,
    Event,
    Observable,
    Outcome,
    Source,
    Target,
    Transport,
)
from .base import Adapter, IngestContext

_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$|^[0-9a-fA-F:]+:[0-9a-fA-F:]+$")

# eventName -> (normalized action, category)
_ACTION_MAP: dict[str, tuple[str, Category]] = {
    "AttachUserPolicy": ("iam.policy.attach", Category.iam),
    "AttachRolePolicy": ("iam.policy.attach", Category.iam),
    "AttachGroupPolicy": ("iam.policy.attach", Category.iam),
    "PutUserPolicy": ("iam.policy.put_inline", Category.iam),
    "PutRolePolicy": ("iam.policy.put_inline", Category.iam),
    "PutGroupPolicy": ("iam.policy.put_inline", Category.iam),
    "CreatePolicyVersion": ("iam.policy.create_version", Category.iam),
    "CreateUser": ("iam.user.create", Category.iam),
    "CreateRole": ("iam.role.create", Category.iam),
    "CreateLoginProfile": ("iam.login_profile.create", Category.iam),
    "UpdateLoginProfile": ("iam.login_profile.update", Category.iam),
    "CreateAccessKey": ("iam.access_key.create", Category.iam),
    "UpdateAccessKey": ("iam.access_key.update", Category.iam),
    "DeactivateMFADevice": ("iam.mfa.deactivate", Category.iam),
    "DeleteVirtualMFADevice": ("iam.mfa.delete", Category.iam),
    "UpdateAssumeRolePolicy": ("iam.role.update_trust", Category.iam),
    "AddUserToGroup": ("iam.group.add_user", Category.iam),
    "ConsoleLogin": ("auth.console.login", Category.auth),
    "AssumeRole": ("auth.assume_role", Category.auth),
    "StopLogging": ("cloudtrail.logging.stop", Category.audit),
    "DeleteTrail": ("cloudtrail.trail.delete", Category.audit),
    "UpdateTrail": ("cloudtrail.trail.update", Category.audit),
    # S3 management events — bucket-level changes that matter for security.
    # Adapter additionally sets extra.public_acl / public_policy / bpa_weakened /
    # versioning_status / mfa_delete_status / logging_disabled where applicable
    # so the s3.yaml rules can match the SIGNAL, not just the API call name.
    "CreateBucket":                         ("s3.bucket.create", Category.storage),
    "DeleteBucket":                         ("s3.bucket.delete", Category.storage),
    "PutBucketAcl":                         ("s3.bucket.acl.put", Category.storage),
    "PutBucketPolicy":                      ("s3.bucket.policy.put", Category.storage),
    "DeleteBucketPolicy":                   ("s3.bucket.policy.delete", Category.storage),
    "PutPublicAccessBlock":                 ("s3.bucket.bpa.put", Category.storage),
    "DeletePublicAccessBlock":              ("s3.bucket.bpa.delete", Category.storage),
    "PutBucketEncryption":                  ("s3.bucket.encryption.put", Category.storage),
    "DeleteBucketEncryption":               ("s3.bucket.encryption.delete", Category.storage),
    "PutBucketVersioning":                  ("s3.bucket.versioning.put", Category.storage),
    "PutBucketLogging":                     ("s3.bucket.logging.put", Category.storage),
    "PutBucketLifecycleConfiguration":      ("s3.bucket.lifecycle.put", Category.storage),
    "PutBucketReplication":                 ("s3.bucket.replication.put", Category.storage),
    "DeleteBucketReplication":              ("s3.bucket.replication.delete", Category.storage),
    "PutObjectLockConfiguration":           ("s3.bucket.object_lock.put", Category.storage),
    # Security groups — adapter flags extra.public_ingress / public_ingress_risky_port.
    "AuthorizeSecurityGroupIngress":        ("network.sg.ingress.add", Category.network),
    "AuthorizeSecurityGroupEgress":         ("network.sg.egress.add", Category.network),
    "RevokeSecurityGroupIngress":           ("network.sg.ingress.remove", Category.network),
    "RevokeSecurityGroupEgress":            ("network.sg.egress.remove", Category.network),
    "CreateSecurityGroup":                  ("network.sg.create", Category.network),
    "DeleteSecurityGroup":                  ("network.sg.delete", Category.network),
    # EC2 hardening + sharing.
    "ModifyInstanceMetadataOptions":        ("compute.imds.modify", Category.compute),
    "ModifyImageAttribute":                 ("compute.ami.modify", Category.compute),
    # ModifyInstanceAttribute is the SAME API for many semantically different
    # actions — SG attach, instance-type change, source/dest check, kernel
    # swap, etc. We map to a generic name and override below when we can
    # detect which sub-action it was from requestParameters.
    "ModifyInstanceAttribute":              ("compute.instance.modify", Category.compute),
    # EBS.
    "ModifySnapshotAttribute":              ("storage.snapshot.modify", Category.storage),
    "ModifyVolume":                         ("storage.volume.modify", Category.storage),
    "CreateVolume":                         ("storage.volume.create", Category.storage),
    "DeleteSnapshot":                       ("storage.snapshot.delete", Category.storage),
    # KMS.
    "DisableKeyRotation":                   ("kms.rotation.disable", Category.iam),
    "EnableKeyRotation":                    ("kms.rotation.enable", Category.iam),
    "PutKeyPolicy":                         ("kms.policy.put", Category.iam),
    "ScheduleKeyDeletion":                  ("kms.key.delete_scheduled", Category.iam),
    "CancelKeyDeletion":                    ("kms.key.delete_cancelled", Category.iam),
    # RDS — adapter flags signals (publicly_accessible, snapshot_made_public,
    # backups_disabled, deletion_protection_off, master_password_change) so
    # detection rules can match the SIGNAL, not just the API call.
    # Instance lifecycle.
    "CreateDBInstance":                     ("rds.instance.create", Category.storage),
    "DeleteDBInstance":                     ("rds.instance.delete", Category.storage),
    "ModifyDBInstance":                     ("rds.instance.modify", Category.storage),
    "RebootDBInstance":                     ("rds.instance.reboot", Category.storage),
    "StartDBInstance":                      ("rds.instance.start", Category.storage),
    "StopDBInstance":                       ("rds.instance.stop", Category.storage),
    "RestoreDBInstanceFromDBSnapshot":      ("rds.instance.restore", Category.storage),
    "RestoreDBInstanceToPointInTime":       ("rds.instance.restore_pit", Category.storage),
    # Snapshots — modify is the sharing surface (the data-exfil one).
    "CreateDBSnapshot":                     ("rds.snapshot.create", Category.storage),
    "DeleteDBSnapshot":                     ("rds.snapshot.delete", Category.storage),
    "ModifyDBSnapshotAttribute":            ("rds.snapshot.modify", Category.storage),
    "CopyDBSnapshot":                       ("rds.snapshot.copy", Category.storage),
    # Parameter / subnet groups — TLS enforcement + logging knobs live here.
    "CreateDBParameterGroup":               ("rds.parameter_group.create", Category.storage),
    "DeleteDBParameterGroup":               ("rds.parameter_group.delete", Category.storage),
    "ModifyDBParameterGroup":               ("rds.parameter_group.modify", Category.storage),
    "ResetDBParameterGroup":                ("rds.parameter_group.reset", Category.storage),
    "ModifyDBSubnetGroup":                  ("rds.subnet_group.modify", Category.storage),
    # Aurora clusters — same shape, different API. Cheap to include.
    "CreateDBCluster":                      ("rds.cluster.create", Category.storage),
    "DeleteDBCluster":                      ("rds.cluster.delete", Category.storage),
    "ModifyDBCluster":                      ("rds.cluster.modify", Category.storage),
    "ModifyDBClusterSnapshotAttribute":     ("rds.cluster_snapshot.modify", Category.storage),
}


# Ports that should never be exposed to 0.0.0.0/0 — open these to the world and
# you've almost certainly screwed up. Web traffic (80/443) is the only public
# port range that we treat as expected.
_RISKY_PORTS = {
    22, 23,                # SSH, telnet
    25, 587, 465,          # SMTP / submission
    139, 445,              # SMB
    389, 636,              # LDAP / LDAPS
    1433, 1521,            # MSSQL, Oracle
    2049,                  # NFS
    2375, 2376,            # Docker
    3306,                  # MySQL
    3389,                  # RDP
    5432,                  # Postgres
    5900, 5901,            # VNC
    6379,                  # Redis
    8086,                  # InfluxDB
    9200, 9300,            # Elasticsearch
    11211,                 # memcached
    27017, 27018,          # MongoDB
}

_ACTOR_TYPE_MAP = {
    "Root": ActorType.root,
    "IAMUser": ActorType.user,
    "AssumedRole": ActorType.role,
    "AWSService": ActorType.service,
    "AWSAccount": ActorType.service,
}


def _parse_time(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _is_ip(value: Any) -> bool:
    return isinstance(value, str) and bool(_IP_RE.match(value))


def _service_from_source(event_source: str) -> str:
    return (event_source or "aws").split(".")[0] or "aws"


def _wildcard_policy(request_params: dict[str, Any]) -> bool:
    doc = request_params.get("policyDocument")
    if not isinstance(doc, str):
        return False
    blob = doc.replace(" ", "")
    return '"Action":"*"' in blob or '"*:*"' in blob or '"Resource":"*"' in blob


def _bucket_policy_is_public(request_params: dict[str, Any]) -> bool:
    """A PutBucketPolicy document is 'public' if any statement has
    Principal: * (or Principal: {"AWS": "*"}) AND Effect: Allow AND no Condition
    that scopes it down. This errs cautiously — any policy with Principal:* and
    no Condition is flagged. Operators can suppress per-bucket if intentional."""
    doc = request_params.get("bucketPolicy") or request_params.get("policy")
    if not isinstance(doc, str):
        return False
    try:
        parsed = json.loads(doc)
    except (ValueError, TypeError):
        return False
    statements = parsed.get("Statement") or []
    if isinstance(statements, dict):
        statements = [statements]
    for s in statements:
        if not isinstance(s, dict):
            continue
        if s.get("Effect") != "Allow":
            continue
        principal = s.get("Principal")
        is_wildcard_principal = (
            principal == "*"
            or (isinstance(principal, dict) and (
                principal.get("AWS") == "*"
                or (isinstance(principal.get("AWS"), list) and "*" in principal["AWS"])
            ))
        )
        if not is_wildcard_principal:
            continue
        # If there's a Condition, we DON'T flag — it might safely scope by IP,
        # VPC endpoint, MFA, etc. The CloudTrail event is still stored; only
        # the public_policy=true *signal* is suppressed.
        if not s.get("Condition"):
            return True
    return False


def _acl_grants_public(request_params: dict[str, Any]) -> bool:
    """A PutBucketAcl is 'public' if any grant targets AllUsers or
    AuthenticatedUsers. Both the canned `x-amz-acl: public-read` style and the
    explicit grantee URI form land in CloudTrail."""
    canned = (request_params.get("x-amz-acl")
              or request_params.get("acl") or "").lower()
    if canned in ("public-read", "public-read-write", "authenticated-read"):
        return True
    blob = json.dumps(request_params).lower()
    return ("global/allusers" in blob) or ("global/authenticatedusers" in blob)


def _bpa_weakened(request_params: dict[str, Any]) -> bool:
    """A PutPublicAccessBlock weakens posture if ANY of the 4 booleans is False
    (or absent). The 'strong' config has all 4 set to true."""
    cfg = request_params.get("PublicAccessBlockConfiguration") or {}
    keys = ("BlockPublicAcls", "IgnorePublicAcls",
            "BlockPublicPolicy", "RestrictPublicBuckets")
    return any(not cfg.get(k, False) for k in keys)


def _versioning_suspended(request_params: dict[str, Any]) -> bool:
    cfg = request_params.get("VersioningConfiguration") or {}
    return str(cfg.get("Status", "")).lower() == "suspended"


def _mfa_delete_disabled(request_params: dict[str, Any]) -> bool:
    cfg = request_params.get("VersioningConfiguration") or {}
    return str(cfg.get("MfaDelete", "")).lower() == "disabled"


def _logging_disabled(request_params: dict[str, Any]) -> bool:
    """PutBucketLogging with no target bucket disables logging."""
    cfg = request_params.get("BucketLoggingStatus") or {}
    return not cfg.get("LoggingEnabled")


# ---------- AWS posture signal detectors ------------------------------------

def _sg_ingress_signals(request_params: dict[str, Any]) -> dict[str, Any]:
    """AuthorizeSecurityGroupIngress requestParameters carry the ingress rules.
    Returns a dict of signals to merge into `extra`:
      - public_ingress: True if any rule opens 0.0.0.0/0 (or ::/0)
      - public_ingress_risky_port: True if a risky port is opened publicly
      - public_ingress_all_traffic: True if proto=-1 or huge range opened publicly
      - public_ports: list of public ports (truncated)
    Handles BOTH shapes CloudTrail uses (nested ipPermissions.items vs. flat)."""
    out: dict[str, Any] = {}
    perms: list[dict[str, Any]] = []
    ipp = request_params.get("ipPermissions")
    if isinstance(ipp, dict):
        items = ipp.get("items") or []
        if isinstance(items, list):
            perms.extend(p for p in items if isinstance(p, dict))
    if not perms and (request_params.get("cidrIp") is not None
                      or request_params.get("fromPort") is not None
                      or request_params.get("ipProtocol") is not None):
        perms.append(request_params)

    public = False
    public_risky = False
    public_all = False
    public_ports: list[int] = []
    for perm in perms:
        cidrs: list[str] = []
        ranges = perm.get("ipRanges")
        if isinstance(ranges, dict):
            for r in (ranges.get("items") or []):
                if isinstance(r, dict) and r.get("cidrIp"):
                    cidrs.append(r["cidrIp"])
        elif perm.get("cidrIp"):
            cidrs.append(perm["cidrIp"])
        v6 = perm.get("ipv6Ranges")
        if isinstance(v6, dict):
            for r in (v6.get("items") or []):
                if isinstance(r, dict) and r.get("cidrIpv6"):
                    cidrs.append(r["cidrIpv6"])
        elif perm.get("cidrIpv6"):
            cidrs.append(perm["cidrIpv6"])
        if not any(c in ("0.0.0.0/0", "::/0") for c in cidrs):
            continue
        public = True
        proto = perm.get("ipProtocol")
        if proto in (-1, "-1", "all", None):
            public_all = True
            continue
        from_p, to_p = perm.get("fromPort"), perm.get("toPort")
        try:
            fp = int(from_p) if from_p is not None else None
            tp = int(to_p) if to_p is not None else fp
        except (TypeError, ValueError):
            continue
        if fp is None:
            continue
        # A huge port range (0..>=1024) is effectively all-traffic public.
        if fp == 0 and tp is not None and tp >= 1024:
            public_all = True
            continue
        if tp is None:
            tp = fp
        for p in range(fp, tp + 1):
            public_ports.append(p)
            if p in _RISKY_PORTS:
                public_risky = True
            if len(public_ports) >= 50:
                break

    if public:
        out["public_ingress"] = True
    if public_risky:
        out["public_ingress_risky_port"] = True
    if public_all:
        out["public_ingress_all_traffic"] = True
    if public_ports:
        out["public_ports"] = public_ports[:50]
    return out


def _imds_weakened(request_params: dict[str, Any]) -> bool:
    """`HttpTokens=optional` lets IMDSv1 work — the well-known SSRF→instance-
    credential-theft vector. Strict secure mode requires `required`."""
    return str(request_params.get("httpTokens", "")).lower() == "optional"


def _snapshot_made_public(request_params: dict[str, Any]) -> bool:
    """ModifySnapshotAttribute granting createVolumePermission to group 'all'
    makes the snapshot publicly restorable — direct exfil path."""
    perm = request_params.get("createVolumePermission") or {}
    if not isinstance(perm, dict):
        return False
    for op in ("add", "items"):
        block = perm.get(op)
        items = block.get("items") if isinstance(block, dict) else (
            block if isinstance(block, list) else [])
        for it in items or []:
            if isinstance(it, dict) and (it.get("group") == "all" or it.get("userId") == "all"):
                return True
    return False


def _ami_made_public(request_params: dict[str, Any]) -> bool:
    """ModifyImageAttribute adding 'all' to launch permissions = public AMI."""
    perm = request_params.get("launchPermission") or {}
    if not isinstance(perm, dict):
        return False
    add = perm.get("add")
    items = add.get("items") if isinstance(add, dict) else (add if isinstance(add, list) else [])
    for it in items or []:
        if isinstance(it, dict) and it.get("group") == "all":
            return True
    return False


def _kms_policy_is_wildcard(request_params: dict[str, Any]) -> bool:
    """PutKeyPolicy with Principal=* and no Condition. Same shape as the S3
    bucket-policy public check."""
    doc = request_params.get("policy")
    if not isinstance(doc, str):
        return False
    try:
        parsed = json.loads(doc)
    except (ValueError, TypeError):
        return False
    statements = parsed.get("Statement") or []
    if isinstance(statements, dict):
        statements = [statements]
    for s in statements:
        if not isinstance(s, dict) or s.get("Effect") != "Allow":
            continue
        p = s.get("Principal")
        is_wild = (p == "*" or (isinstance(p, dict) and (
            p.get("AWS") == "*"
            or (isinstance(p.get("AWS"), list) and "*" in p["AWS"]))))
        if is_wild and not s.get("Condition"):
            return True
    return False


# ---- RDS signal detectors --------------------------------------------------
#
# All pure-data checks against requestParameters. Return the flags the adapter
# adds to event.extra so detection rules can match the SIGNAL rather than the
# bare API name. Important: ModifyDBInstance fires for every routine change
# (storage resize, tag edit, parameter group swap) — we only flag fields that
# actually carry security meaning.

def _rds_publicly_accessible(rp: dict[str, Any]) -> bool:
    # Both Create and Modify use the same param name. Boolean True = exposed.
    return rp.get("publiclyAccessible") is True


def _rds_backups_disabled(rp: dict[str, Any]) -> bool:
    # 0-day retention means automated backups are off. Anything >0 is fine.
    period = rp.get("backupRetentionPeriod")
    return isinstance(period, int) and period == 0


def _rds_deletion_protection_off(rp: dict[str, Any]) -> bool:
    # Only flag when the call EXPLICITLY sets it false — omission means
    # "no change" and we shouldn't fire on every routine modify.
    return rp.get("deletionProtection") is False


def _rds_unencrypted_at_creation(rp: dict[str, Any]) -> bool:
    # storageEncrypted defaults to False historically; flag the explicit False
    # (or absence on Create) so audit logs catch unencrypted DBs at birth.
    return rp.get("storageEncrypted") is False


def _rds_master_password_change(rp: dict[str, Any]) -> bool:
    # If the field is present in the request (even masked to "****"), the
    # master password was rotated. Could be legit rotation or compromise —
    # the rule decides; the adapter just surfaces the fact.
    return "masterUserPassword" in rp


def _rds_snapshot_made_public(rp: dict[str, Any]) -> bool:
    # ModifyDBSnapshotAttribute / ModifyDBClusterSnapshotAttribute with
    # AttributeName=restore + ValuesToAdd containing "all" = shared with everyone.
    if rp.get("attributeName") != "restore":
        return False
    add = rp.get("valuesToAdd") or []
    if isinstance(add, list) and "all" in add:
        return True
    return False


def _rds_iam_auth_disabled(rp: dict[str, Any]) -> bool:
    # Explicit False = IAM database auth turned off (relies on password alone).
    return rp.get("enableIAMDatabaseAuthentication") is False


def _rds_param_changes_security(rp: dict[str, Any]) -> list[str]:
    """If a parameter-group modify touches a security-relevant parameter
    (`rds.force_ssl`, `log_connections`, `log_statement`, etc.), return the
    names changed. Empty list = nothing security-relevant touched."""
    params = rp.get("parameters") or []
    if not isinstance(params, list):
        return []
    watched = {
        "rds.force_ssl",
        "log_connections", "log_disconnections", "log_statement",
        "log_min_duration_statement",
        "ssl",  # the MySQL ssl param
        "require_secure_transport",
    }
    hits: list[str] = []
    for p in params:
        if not isinstance(p, dict):
            continue
        name = p.get("parameterName")
        if name in watched:
            hits.append(name)
    return hits


def _extract_sg_ids_from_modify(request_params: dict[str, Any]) -> list[str]:
    """ModifyInstanceAttribute carries the new SG list in `groupSet.items[].groupId`
    on the EC2-classic-flavored shape, or sometimes as a flat `groups[]` list.
    We support both. Returns the list of SG ids the operator attached (which
    REPLACES the previous set — there's no "added" / "removed" distinction in
    the event payload itself; you'd need DescribeInstances before/after to
    compute the delta)."""
    out: list[str] = []
    group_set = request_params.get("groupSet")
    if isinstance(group_set, dict):
        items = group_set.get("items")
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("groupId"):
                    out.append(str(it["groupId"]))
    # Flat list shape (less common but observed in some SDK versions)
    groups = request_params.get("groups")
    if isinstance(groups, list):
        for g in groups:
            if isinstance(g, str) and g.startswith("sg-"):
                out.append(g)
            elif isinstance(g, dict) and g.get("groupId"):
                out.append(str(g["groupId"]))
    return out


class AwsCloudTrailAdapter(Adapter):
    module = "aws.cloudtrail"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict):
            return []
        # EventBridge envelope wraps the record in `detail`; otherwise it's raw.
        detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else raw
        if "eventName" not in detail:
            return []

        event_name = detail.get("eventName", "")
        event_source = detail.get("eventSource", "")
        service = _service_from_source(event_source)
        action, category = _ACTION_MAP.get(
            event_name, (f"aws.{service}.{event_name.lower()}", Category.audit)
        )

        identity = detail.get("userIdentity") or {}
        identity_type = identity.get("type", "")
        is_root = identity_type == "Root"
        principal = identity.get("arn") or identity.get("userName") or ("root" if is_root else None)
        src_ip = detail.get("sourceIPAddress")
        source_ip = src_ip if _is_ip(src_ip) else None

        # Outcome: ConsoleLogin reports in responseElements; otherwise errorCode.
        response = detail.get("responseElements") or {}
        if event_name == "ConsoleLogin":
            outcome = (
                Outcome.success
                if str(response.get("ConsoleLogin", "")).lower() == "success"
                else Outcome.failure
            )
        else:
            outcome = Outcome.failure if detail.get("errorCode") else Outcome.success

        request_params = detail.get("requestParameters") or {}
        target_id = (
            request_params.get("policyArn")
            or request_params.get("roleName")
            or request_params.get("userName")
            or request_params.get("groupName")
            or request_params.get("accessKeyId")
            # For S3 events: bucket name. Lives in requestParameters.bucketName
            # for almost every S3 management call.
            or request_params.get("bucketName")
            # RDS — different API uses different name fields. Pick the first
            # one present; whichever fired will have exactly one populated.
            or request_params.get("dBInstanceIdentifier")
            or request_params.get("dBClusterIdentifier")
            or request_params.get("dBSnapshotIdentifier")
            or request_params.get("dBClusterSnapshotIdentifier")
            or request_params.get("dBParameterGroupName")
            or request_params.get("dBSubnetGroupName")
        )

        observables: list[Observable] = []
        seen: set[tuple[str, str]] = set()

        def add_obs(otype: str, value: Any) -> None:
            if value and (otype, str(value)) not in seen:
                observables.append(Observable(type=otype, value=str(value)))
                seen.add((otype, str(value)))

        if principal and str(principal).startswith("arn:"):
            add_obs("arn", principal)
        add_obs("ip", source_ip)
        add_obs("arn", request_params.get("policyArn"))
        add_obs("access_key", request_params.get("accessKeyId"))
        if request_params.get("userName"):
            add_obs("user", request_params["userName"])

        additional = detail.get("additionalEventData") or {}
        extra = {
            "event_name": event_name,
            "event_source": event_source,
            "mfa_used": additional.get("MFAUsed"),
            "error_code": detail.get("errorCode"),
            "error_message": detail.get("errorMessage"),
        }
        if action in ("iam.policy.put_inline", "iam.policy.create_version") and _wildcard_policy(request_params):
            extra["wildcard_policy"] = True

        # S3-specific detection signals — flagged so rules in s3.yaml can match
        # the SIGNAL not just the API name. Each is a one-shot pure-data check
        # against requestParameters; storage / pipeline / projection are
        # untouched.
        if action == "s3.bucket.acl.put" and _acl_grants_public(request_params):
            extra["public_acl"] = True
        if action == "s3.bucket.policy.put" and _bucket_policy_is_public(request_params):
            extra["public_policy"] = True
        if action == "s3.bucket.bpa.put" and _bpa_weakened(request_params):
            extra["bpa_weakened"] = True
        if action == "s3.bucket.versioning.put":
            if _versioning_suspended(request_params):
                extra["versioning_suspended"] = True
            if _mfa_delete_disabled(request_params):
                extra["mfa_delete_disabled"] = True
        if action == "s3.bucket.logging.put" and _logging_disabled(request_params):
            extra["logging_disabled"] = True

        # AWS posture signals — same shape as the S3 ones above. Rules in
        # aws_posture.yaml match these flags.
        if action == "network.sg.ingress.add":
            extra.update(_sg_ingress_signals(request_params))
        if action == "compute.imds.modify" and _imds_weakened(request_params):
            extra["imdsv1_enabled"] = True
        if action == "storage.snapshot.modify" and _snapshot_made_public(request_params):
            extra["snapshot_made_public"] = True
        if action == "compute.ami.modify" and _ami_made_public(request_params):
            extra["ami_made_public"] = True
        if action == "kms.policy.put" and _kms_policy_is_wildcard(request_params):
            extra["kms_wildcard_policy"] = True

        # RDS signals — same pattern as S3/SG above. Pure data on requestParameters.
        # Instance create / modify share the "exposed?" flags; snapshot.modify
        # carries the "shared with everyone" flag.
        if action in ("rds.instance.create", "rds.instance.modify", "rds.cluster.create", "rds.cluster.modify"):
            if _rds_publicly_accessible(request_params):
                extra["rds_publicly_accessible"] = True
            if _rds_backups_disabled(request_params):
                extra["rds_backups_disabled"] = True
            if _rds_deletion_protection_off(request_params):
                extra["rds_deletion_protection_off"] = True
            if _rds_master_password_change(request_params):
                extra["rds_master_password_change"] = True
            if _rds_iam_auth_disabled(request_params):
                extra["rds_iam_auth_disabled"] = True
        if action in ("rds.instance.create", "rds.cluster.create") and _rds_unencrypted_at_creation(request_params):
            extra["rds_unencrypted_at_creation"] = True
        if action in ("rds.snapshot.modify", "rds.cluster_snapshot.modify") and _rds_snapshot_made_public(request_params):
            extra["rds_snapshot_made_public"] = True
        if action == "rds.parameter_group.modify":
            hits = _rds_param_changes_security(request_params)
            if hits:
                extra["rds_security_params_changed"] = hits

        # ModifyInstanceAttribute split — same API, very different semantics.
        # When groupSet/groups is present, the operator attached/changed which
        # SGs apply to this instance. Re-tag as a network event so it lands
        # in the /iam SG section, and stamp the SG ids into extras.
        if action == "compute.instance.modify":
            sg_ids = _extract_sg_ids_from_modify(request_params)
            if sg_ids:
                action = "network.sg.instance_attach"
                category = Category.network
                extra["instance_id"] = request_params.get("instanceId")
                extra["sg_ids"] = sg_ids
                # Override the target so the IAM page's Target column shows
                # something meaningful (instance id, not the SG ARNs).
                if not target_id:
                    target_id = request_params.get("instanceId")

        event_id_src = detail.get("eventID")
        kwargs: dict[str, Any] = {}
        if event_id_src:
            kwargs["event_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudtrail:{event_id_src}"))

        event = Event(
            source=Source(
                module=self.module,
                vendor="aws",
                account=raw.get("account") or detail.get("recipientAccountId"),
                region=raw.get("region") or detail.get("awsRegion"),
                transport=Transport(ctx.transport) if ctx.transport in Transport._value2member_map_ else Transport.queue,
            ),
            event_time=_parse_time(detail.get("eventTime") or raw.get("time")),
            category=category,
            action=action,
            outcome=outcome,
            actor=Actor(
                principal=principal,
                type=_ACTOR_TYPE_MAP.get(identity_type),
                is_root=is_root,
                source_ip=source_ip,
                user_agent=detail.get("userAgent"),
            ),
            target=Target(id=target_id, type=f"aws.{service}"),
            observables=observables,
            extra={k: v for k, v in extra.items() if v is not None},
            raw=raw,
            **kwargs,
        )
        return [event]
