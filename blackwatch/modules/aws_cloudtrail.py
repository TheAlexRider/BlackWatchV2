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

_SECRET_PAYLOAD_KEYS = {"secretstring", "secretbinary", "secretvalue", "plaintext"}


def _redact_secret_payload(value: Any) -> Any:
    """Return a copy of a CloudTrail payload with secret values removed.

    Secrets Manager may place sensitive fields at different nesting levels in
    requestParameters or responseElements, and SDK/event producers vary the
    casing and punctuation of those keys. Keep all surrounding metadata for
    audit and notification use, but never retain the value under a sensitive
    field in Event.raw (which is persisted as JSONB).
    """
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, child in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            redacted[key] = "[REDACTED]" if normalized_key in _SECRET_PAYLOAD_KEYS else _redact_secret_payload(child)
        return redacted
    if isinstance(value, list):
        return [_redact_secret_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_secret_payload(item) for item in value)
    return value

# eventName -> (normalized action, category)
_ACTION_MAP: dict[str, tuple[str, Category]] = {
    # --- IAM identity ----------------------------------------------------
    "CreateUser": ("iam.user.create", Category.iam),
    "DeleteUser": ("iam.user.delete", Category.iam),
    "UpdateUser": ("iam.user.update", Category.iam),
    "CreateRole": ("iam.role.create", Category.iam),
    "DeleteRole": ("iam.role.delete", Category.iam),
    "CreateGroup": ("iam.group.create", Category.iam),
    "DeleteGroup": ("iam.group.delete", Category.iam),
    "AddUserToGroup": ("iam.group.add_user", Category.iam),
    "RemoveUserFromGroup": ("iam.group.remove_user", Category.iam),
    # --- IAM credentials -------------------------------------------------
    "CreateLoginProfile": ("iam.login_profile.create", Category.iam),
    "UpdateLoginProfile": ("iam.login_profile.update", Category.iam),
    "DeleteLoginProfile": ("iam.login_profile.delete", Category.iam),
    "CreateAccessKey": ("iam.access_key.create", Category.iam),
    "UpdateAccessKey": ("iam.access_key.update", Category.iam),
    "DeleteAccessKey": ("iam.access_key.delete", Category.iam),
    "EnableMFADevice": ("iam.mfa.enable", Category.iam),
    "DeactivateMFADevice": ("iam.mfa.deactivate", Category.iam),
    "DeleteVirtualMFADevice": ("iam.mfa.delete", Category.iam),
    # --- IAM policy ------------------------------------------------------
    "AttachUserPolicy": ("iam.policy.attach", Category.iam),
    "AttachRolePolicy": ("iam.policy.attach", Category.iam),
    "AttachGroupPolicy": ("iam.policy.attach", Category.iam),
    "DetachUserPolicy": ("iam.policy.detach", Category.iam),
    "DetachRolePolicy": ("iam.policy.detach", Category.iam),
    "DetachGroupPolicy": ("iam.policy.detach", Category.iam),
    "PutUserPolicy": ("iam.policy.put_inline", Category.iam),
    "PutRolePolicy": ("iam.policy.put_inline", Category.iam),
    "PutGroupPolicy": ("iam.policy.put_inline", Category.iam),
    "DeleteUserPolicy": ("iam.policy.delete_inline", Category.iam),
    "DeleteRolePolicy": ("iam.policy.delete_inline", Category.iam),
    "DeleteGroupPolicy": ("iam.policy.delete_inline", Category.iam),
    "CreatePolicy": ("iam.policy.create", Category.iam),
    "DeletePolicy": ("iam.policy.delete", Category.iam),
    "CreatePolicyVersion": ("iam.policy.create_version", Category.iam),
    "DeletePolicyVersion": ("iam.policy.delete_version", Category.iam),
    "UpdateAssumeRolePolicy": ("iam.role.update_trust", Category.iam),
    "PutRolePermissionsBoundary": ("iam.role.boundary.put", Category.iam),
    "DeleteRolePermissionsBoundary": ("iam.role.boundary.delete", Category.iam),
    "PutUserPermissionsBoundary": ("iam.user.boundary.put", Category.iam),
    "DeleteUserPermissionsBoundary": ("iam.user.boundary.delete", Category.iam),
    # --- Auth ------------------------------------------------------------
    # AssumeRole proper is excluded: too noisy (every service hop fires it).
    # SAML / WebIdentity are KEPT — those are human SSO sign-ins.
    "ConsoleLogin": ("auth.console.login", Category.auth),
    "AssumeRoleWithSAML": ("auth.federated.login", Category.auth),
    "AssumeRoleWithWebIdentity": ("auth.federated.login", Category.auth),
    # --- CloudTrail tamper ----------------------------------------------
    "StopLogging": ("cloudtrail.logging.stop", Category.audit),
    "StartLogging": ("cloudtrail.logging.start", Category.audit),
    "DeleteTrail": ("cloudtrail.trail.delete", Category.audit),
    "UpdateTrail": ("cloudtrail.trail.update", Category.audit),
    "CreateTrail": ("cloudtrail.trail.create", Category.audit),
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
    # KMS — key lifecycle + grants (cross-account decrypt vector).
    "CreateKey":                            ("kms.key.create", Category.iam),
    "EnableKey":                            ("kms.key.enable", Category.iam),
    "DisableKey":                           ("kms.key.disable", Category.iam),
    "DisableKeyRotation":                   ("kms.rotation.disable", Category.iam),
    "EnableKeyRotation":                    ("kms.rotation.enable", Category.iam),
    "PutKeyPolicy":                         ("kms.policy.put", Category.iam),
    "ScheduleKeyDeletion":                  ("kms.key.delete_scheduled", Category.iam),
    "CancelKeyDeletion":                    ("kms.key.delete_cancelled", Category.iam),
    "CreateGrant":                          ("kms.grant.create", Category.iam),
    "RetireGrant":                          ("kms.grant.retire", Category.iam),
    "RevokeGrant":                          ("kms.grant.revoke", Category.iam),
    # --- Network topology (VPC / IGW / NAT / route / peering) ----------
    # Not security-group rules — these are the SHAPE of the network. Adding
    # an IGW or accepting a peering connection is how you build a new exfil
    # path, so we track them all.
    "CreateVpc":                            ("network.vpc.create", Category.network),
    "DeleteVpc":                            ("network.vpc.delete", Category.network),
    "ModifyVpcAttribute":                   ("network.vpc.modify", Category.network),
    "CreateSubnet":                         ("network.subnet.create", Category.network),
    "DeleteSubnet":                         ("network.subnet.delete", Category.network),
    "CreateInternetGateway":                ("network.igw.create", Category.network),
    "DeleteInternetGateway":                ("network.igw.delete", Category.network),
    "AttachInternetGateway":                ("network.igw.attach", Category.network),
    "DetachInternetGateway":                ("network.igw.detach", Category.network),
    "CreateNatGateway":                     ("network.nat.create", Category.network),
    "DeleteNatGateway":                     ("network.nat.delete", Category.network),
    "CreateRouteTable":                     ("network.route_table.create", Category.network),
    "DeleteRouteTable":                     ("network.route_table.delete", Category.network),
    "AssociateRouteTable":                  ("network.route_table.associate", Category.network),
    "CreateRoute":                          ("network.route.create", Category.network),
    "DeleteRoute":                          ("network.route.delete", Category.network),
    "ReplaceRoute":                         ("network.route.replace", Category.network),
    "CreateNetworkAclEntry":                ("network.nacl.entry.create", Category.network),
    "ReplaceNetworkAclEntry":               ("network.nacl.entry.replace", Category.network),
    "DeleteNetworkAclEntry":                ("network.nacl.entry.delete", Category.network),
    "CreateVpcPeeringConnection":           ("network.peering.create", Category.network),
    "AcceptVpcPeeringConnection":           ("network.peering.accept", Category.network),
    "DeleteVpcPeeringConnection":           ("network.peering.delete", Category.network),
    "CreateTransitGatewayPeeringAttachment": ("network.tgw_peering.create", Category.network),
    "AcceptTransitGatewayPeeringAttachment": ("network.tgw_peering.accept", Category.network),
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
    # --- EFS -------------------------------------------------------------
    # Mount targets are the ingress path for NFS — a new one puts your
    # filesystem inside another subnet. SG changes on a mount target can
    # broaden who can reach patient data over 2049/tcp.
    "CreateFileSystem":                     ("efs.filesystem.create", Category.storage),
    "DeleteFileSystem":                     ("efs.filesystem.delete", Category.storage),
    "PutFileSystemPolicy":                  ("efs.filesystem.policy.put", Category.storage),
    "DeleteFileSystemPolicy":               ("efs.filesystem.policy.delete", Category.storage),
    "CreateMountTarget":                    ("efs.mount_target.create", Category.storage),
    "DeleteMountTarget":                    ("efs.mount_target.delete", Category.storage),
    "ModifyMountTargetSecurityGroups":      ("efs.mount_target.sg.modify", Category.storage),
    # --- AWS Backup -----------------------------------------------------
    # Recovery-point/vault delete = destroying restore capability. Vault
    # access policy widen or cross-account copy = exfil channel for backups.
    "CreateBackupVault":                    ("backup.vault.create", Category.storage),
    "DeleteBackupVault":                    ("backup.vault.delete", Category.storage),
    "PutBackupVaultAccessPolicy":           ("backup.vault.policy.put", Category.storage),
    "DeleteBackupVaultAccessPolicy":        ("backup.vault.policy.delete", Category.storage),
    "DeleteRecoveryPoint":                  ("backup.recovery_point.delete", Category.storage),
    "StartCopyJob":                         ("backup.copy_job.start", Category.storage),
    # --- Secrets Manager -----------------------------------------------
    # GetSecretValue is the raw access event — expected to be voluminous;
    # UEBA catches the anomalies (first-seen principal / IP). The rest are
    # low-volume management events worth flagging directly.
    "CreateSecret":                         ("secrets.secret.create", Category.iam),
    "DeleteSecret":                         ("secrets.secret.delete", Category.iam),
    "UpdateSecret":                         ("secrets.secret.update", Category.iam),
    "RestoreSecret":                        ("secrets.secret.restore", Category.iam),
    "GetSecretValue":                       ("secrets.secret.get_value", Category.iam),
}


# The set of CloudTrail eventName values this adapter knows how to normalize.
# The EventBridge rule in front of the Lambda MUST forward exactly these — any
# other eventName is noise that wastes SQS quota, DB rows, and projector cycles.
# Print the JSON form with `python -m scripts.iam_lambda_allowlist`.
LAMBDA_ALLOWLIST: tuple[str, ...] = tuple(sorted(_ACTION_MAP.keys()))


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
    public_cidrs: list[str] = []
    public_proto: str | None = None
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
        for c in cidrs:
            if c in ("0.0.0.0/0", "::/0") and c not in public_cidrs:
                public_cidrs.append(c)
        proto = perm.get("ipProtocol")
        if public_proto is None and proto not in (None, -1, "-1"):
            public_proto = str(proto)
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
    if public_cidrs:
        out["public_cidrs"] = public_cidrs
    if public_proto:
        out["public_proto"] = public_proto
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


def _snapshot_cross_account_share(request_params: dict[str, Any]) -> list[str] | None:
    """ModifySnapshotAttribute adding a specific AWS account (not 'all') to
    createVolumePermission. That account can now restore the snapshot as its
    own volume — silent exfil to an attacker-controlled account. Returns the
    list of account IDs added, or None if not a cross-account share."""
    perm = request_params.get("createVolumePermission") or {}
    if not isinstance(perm, dict):
        return None
    accounts: list[str] = []
    for op in ("add", "items"):
        block = perm.get(op)
        items = block.get("items") if isinstance(block, dict) else (
            block if isinstance(block, list) else [])
        for it in items or []:
            if not isinstance(it, dict):
                continue
            uid = it.get("userId")
            if uid and uid != "all":
                accounts.append(str(uid))
    return accounts or None


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


def _ami_cross_account_share(request_params: dict[str, Any]) -> list[str] | None:
    """ModifyImageAttribute adding specific accounts to launchPermission. Same
    exfil shape as EBS snapshot cross-account share but for AMIs."""
    perm = request_params.get("launchPermission") or {}
    if not isinstance(perm, dict):
        return None
    add = perm.get("add")
    items = add.get("items") if isinstance(add, dict) else (add if isinstance(add, list) else [])
    accounts: list[str] = []
    for it in items or []:
        if isinstance(it, dict):
            uid = it.get("userId")
            if uid:
                accounts.append(str(uid))
    return accounts or None


def _policy_doc_is_wildcard(doc: Any) -> bool:
    """Generic resource-policy wildcard check used by KMS/Backup vault/EFS
    filesystem policies. Returns True if any Effect=Allow statement has
    Principal="*" (or AWS="*") AND no Condition — the classic public-share
    misconfiguration."""
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


def _kms_policy_is_wildcard(request_params: dict[str, Any]) -> bool:
    """PutKeyPolicy with Principal=* and no Condition."""
    return _policy_doc_is_wildcard(request_params.get("policy"))


def _backup_copy_cross_account(rp: dict[str, Any]) -> str | None:
    """StartCopyJob with a destinationBackupVaultArn in a different account
    than the source. Returns the destination account ID or None."""
    dest_arn = rp.get("destinationBackupVaultArn")
    if not isinstance(dest_arn, str):
        return None
    parts = dest_arn.split(":")
    if len(parts) < 5:
        return None
    return parts[4] or None


def _efs_mount_target_sg_added(rp: dict[str, Any]) -> list[str]:
    """ModifyMountTargetSecurityGroups returns the SG list being applied.
    Any change is worth flagging; correlation with SG rules happens elsewhere."""
    sgs = rp.get("securityGroups") or []
    if isinstance(sgs, list):
        return [str(s) for s in sgs]
    return []


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


def _rds_snapshot_cross_account_share(rp: dict[str, Any]) -> list[str] | None:
    """Cross-account (not public) share of an RDS snapshot — attacker-controlled
    account can now restore your patient DB as its own instance."""
    if rp.get("attributeName") != "restore":
        return None
    add = rp.get("valuesToAdd") or []
    if not isinstance(add, list):
        return None
    accounts = [str(v) for v in add if v and v != "all"]
    return accounts or None


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


# ---------- Friendly-message synthesis --------------------------------------
#
# CloudTrail action names like `network.sg.ingress.add` are accurate but ugly
# in Slack. For high-signal events we synthesize a one-line human-readable
# description and stash it in `extra.message`. The notification template
# (`event.extra.message or event.action`) picks it up automatically. None
# return value means "no special message — let the template fall back to the
# raw action name."

def _friendly_message(action: str, extra: dict[str, Any], request_params: dict[str, Any],
                      target_id: Any) -> str | None:
    """Return a short one-line description of WHAT happened. The template
    appends ` — {actor.principal} from {actor.source_ip} on {target}` after
    this, so the message should NOT repeat those — only describe the event."""

    # --- Network: SG ingress (the alert with no detail before this fix) ----
    # CIDR stays in the message because it's the *exposure*, not the target.
    # The target (sg-id) is appended automatically by the template.
    if action == "network.sg.ingress.add":
        cidr = (extra.get("public_cidrs") or ["0.0.0.0/0"])[0]
        proto = extra.get("public_proto") or "tcp"
        if extra.get("public_ingress_all_traffic"):
            return f"ALL traffic opened to {cidr}"
        if extra.get("public_ingress_risky_port"):
            ports = extra.get("public_ports") or []
            port_str = ",".join(str(p) for p in ports[:3]) + ("…" if len(ports) > 3 else "")
            return f"Risky public port {proto}/{port_str} opened to {cidr}"
        if extra.get("public_ingress"):
            ports = extra.get("public_ports") or []
            port_str = ",".join(str(p) for p in ports[:3]) + ("…" if len(ports) > 3 else "")
            return f"Public ingress {proto}/{port_str} opened to {cidr}"
        return None  # private-only ingress — let action through

    # --- IAM identity / credentials / policy -------------------------------
    if action == "iam.user.create":      return "IAM user created"
    if action == "iam.user.delete":      return "IAM user deleted"
    if action == "iam.role.create":      return "IAM role created"
    if action == "iam.role.delete":      return "IAM role deleted"
    if action == "iam.role.update_trust":
        return "Role trust policy modified"
    if action == "iam.access_key.create": return "IAM access key created"
    if action == "iam.access_key.delete": return "IAM access key deleted"
    if action == "iam.login_profile.create":
        return "Console password set on IAM user"
    if action == "iam.mfa.deactivate":   return "MFA device deactivated"
    if action == "iam.mfa.delete":       return "MFA device deleted"
    if action == "iam.policy.attach":
        tgt = str(target_id) if target_id else ""
        if "AdministratorAccess" in tgt:
            return "AdministratorAccess policy attached"
        return None
    if action == "iam.policy.put_inline" and extra.get("wildcard_policy"):
        return "Wildcard (*) inline policy applied"
    if action == "iam.policy.create_version" and extra.get("wildcard_policy"):
        return "Wildcard (*) policy version created"

    # --- CloudTrail tamper -------------------------------------------------
    if action == "cloudtrail.logging.stop":
        return "CloudTrail logging stopped"
    if action == "cloudtrail.trail.delete":
        return "CloudTrail trail deleted"
    if action == "cloudtrail.trail.update":
        return "CloudTrail trail modified"

    # --- KMS ---------------------------------------------------------------
    if action == "kms.key.disable":             return "KMS key disabled"
    if action == "kms.key.delete_scheduled":    return "KMS key scheduled for deletion"
    if action == "kms.policy.put" and extra.get("kms_wildcard_policy"):
        return "KMS key policy granted to wildcard principal"
    if action == "kms.grant.create":            return "KMS grant created"

    # --- Storage / compute exposure ----------------------------------------
    if action == "storage.snapshot.modify" and extra.get("snapshot_made_public"):
        return "EBS snapshot shared publicly"
    if action == "storage.snapshot.modify" and extra.get("snapshot_cross_account_share"):
        accts = extra["snapshot_cross_account_share"]
        return f"EBS snapshot shared with account(s): {','.join(accts[:3])}"
    if action == "compute.ami.modify" and extra.get("ami_made_public"):
        return "AMI made public"
    if action == "compute.ami.modify" and extra.get("ami_cross_account_share"):
        accts = extra["ami_cross_account_share"]
        return f"AMI shared with account(s): {','.join(accts[:3])}"
    if action == "compute.imds.modify" and extra.get("imdsv1_enabled"):
        return "IMDSv1 re-enabled (SSRF risk)"

    # --- RDS ---------------------------------------------------------------
    if action in ("rds.instance.create", "rds.instance.modify",
                  "rds.cluster.create", "rds.cluster.modify"):
        if extra.get("rds_publicly_accessible"):
            return "RDS instance set to publicly accessible"
        if extra.get("rds_backups_disabled"):
            return "RDS automated backups disabled"
        if extra.get("rds_deletion_protection_off"):
            return "RDS deletion protection disabled"
        if extra.get("rds_master_password_change"):
            return "RDS master password rotated"
    if action in ("rds.snapshot.modify", "rds.cluster_snapshot.modify") and extra.get("rds_snapshot_made_public"):
        return "RDS snapshot shared publicly"
    if action in ("rds.snapshot.modify", "rds.cluster_snapshot.modify") and extra.get("rds_snapshot_cross_account_share"):
        accts = extra["rds_snapshot_cross_account_share"]
        return f"RDS snapshot shared with account(s): {','.join(accts[:3])}"

    # --- EFS ---------------------------------------------------------------
    if action == "efs.filesystem.policy.put" and extra.get("efs_policy_wildcard"):
        return "EFS filesystem policy granted to wildcard principal"
    if action == "efs.mount_target.create":
        return "EFS mount target created (new NFS ingress path)"
    if action == "efs.mount_target.delete":
        return "EFS mount target deleted"
    if action == "efs.mount_target.sg.modify":
        sgs = extra.get("efs_mount_target_sgs") or []
        return f"EFS mount target SGs changed to {','.join(sgs[:3])}"

    # --- AWS Backup --------------------------------------------------------
    if action == "backup.recovery_point.delete":
        return "Backup recovery point deleted"
    if action == "backup.vault.delete":
        return "Backup vault deleted"
    if action == "backup.vault.policy.put" and extra.get("backup_vault_policy_wildcard"):
        return "Backup vault policy granted to wildcard principal"
    if action == "backup.copy_job.start" and extra.get("backup_copy_dest_account"):
        return f"Backup copy started to account {extra['backup_copy_dest_account']}"

    # --- Secrets Manager ---------------------------------------------------
    if action == "secrets.secret.delete":
        return "Secret scheduled for deletion"
    if action == "secrets.secret.restore":
        return "Secret restored (undelete)"

    # --- S3 ----------------------------------------------------------------
    if action == "s3.bucket.policy.put" and extra.get("public_policy"):
        return "S3 bucket policy made public"
    if action == "s3.bucket.acl.put" and extra.get("public_acl"):
        return "S3 bucket ACL made public"
    if action == "s3.bucket.bpa.put" and extra.get("bpa_weakened"):
        return "S3 Block Public Access weakened"
    if action == "s3.bucket.bpa.delete":
        return "S3 Block Public Access removed"
    if action == "s3.bucket.encryption.delete":
        return "S3 bucket encryption removed"
    if action == "s3.bucket.delete":
        return "S3 bucket deleted"

    # --- Auth --------------------------------------------------------------
    if action == "auth.console.login":
        kind = extra.get("login_kind", "iam")
        if extra.get("error_code"):
            return f"Console login FAILED ({kind})"
        return f"Console login succeeded ({kind})"
    if action == "auth.federated.login":
        if extra.get("error_code"):
            return "Federated SSO login FAILED"
        return "Federated SSO login"

    return None


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
            # Network — VPC / SG / IGW / route / NAT / NACL / peering ids.
            or request_params.get("groupId")
            or request_params.get("vpcId")
            or request_params.get("subnetId")
            or request_params.get("internetGatewayId")
            or request_params.get("natGatewayId")
            or request_params.get("routeTableId")
            or request_params.get("networkAclId")
            or request_params.get("vpcPeeringConnectionId")
            # EC2 compute / storage.
            or request_params.get("instanceId")
            or request_params.get("imageId")
            or request_params.get("snapshotId")
            or request_params.get("volumeId")
            # KMS — keyId is the UUID or ARN of the key.
            or request_params.get("keyId")
            # Secrets Manager — secret name/ARN is carried as SecretId.
            or request_params.get("secretId")
            or request_params.get("name")
            # AWS Backup resources.
            or request_params.get("backupVaultName")
            or request_params.get("backupVaultArn")
            or request_params.get("recoveryPointArn")
            or request_params.get("recoveryPointId")
            # EFS — file-system and mount-target identifiers.
            or request_params.get("fileSystemId")
            or request_params.get("filesystemId")
            or request_params.get("mountTargetId")
            # EFS — file-system and mount-target identifiers.
            or request_params.get("fileSystemId")
            or request_params.get("filesystemId")
            or request_params.get("mountTargetId")
            # CloudTrail — trail mgmt events use `name` for the trail name.
            or (request_params.get("name") if str(event_source).startswith("cloudtrail.") else None)
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
        if action in {"network.igw.attach", "network.peering.accept", "network.tgw_peering.accept", "network.sg.ingress.add"}:
            def set_network(name: str, value: Any) -> None:
                if value is not None and value != "":
                    extra[name] = value

            set_network("vpc_id", request_params.get("vpcId"))
            set_network("subnet_id", request_params.get("subnetId"))
            set_network("gateway_id", request_params.get("internetGatewayId"))
            set_network("peering_id", request_params.get("vpcPeeringConnectionId") or request_params.get("transitGatewayAttachmentId"))
            set_network("security_group_id", request_params.get("groupId"))
            response_network = response.get("vpcPeeringConnection") or response.get("transitGatewayPeeringAttachment") or {}
            if isinstance(response_network, dict):
                set_network("peering_id", response_network.get("vpcPeeringConnectionId") or response_network.get("transitGatewayAttachmentId"))
                requester = response_network.get("requesterVpcInfo") or response_network.get("requesterTgwInfo") or {}
                accepter = response_network.get("accepterVpcInfo") or response_network.get("accepterTgwInfo") or {}
                if isinstance(requester, dict):
                    set_network("source_vpc_id", requester.get("vpcId") or requester.get("transitGatewayId"))
                    set_network("source_account", requester.get("ownerId") or requester.get("ownerAccountId"))
                    set_network("source_region", requester.get("region"))
                if isinstance(accepter, dict):
                    set_network("destination_vpc_id", accepter.get("vpcId") or accepter.get("transitGatewayId"))
                    set_network("destination_account", accepter.get("ownerId") or accepter.get("ownerAccountId"))
                    set_network("destination_region", accepter.get("region"))
                set_network("destination_account", response_network.get("peerAccountId"))
                set_network("destination_region", response_network.get("peerRegion"))
            if action == "network.sg.ingress.add":
                permissions = request_params.get("ipPermissions") or {}
                items = permissions.get("items") if isinstance(permissions, dict) else None
                permission = items[0] if isinstance(items, list) and items else request_params
                if isinstance(permission, dict):
                    set_network("protocol", permission.get("ipProtocol"))
                    set_network("from_port", permission.get("fromPort"))
                    set_network("to_port", permission.get("toPort"))
                    from_port, to_port = permission.get("fromPort"), permission.get("toPort")
                    if from_port is not None:
                        extra["port_range"] = str(from_port) if to_port in (None, from_port) else f"{from_port}-{to_port}"
                signals = _sg_ingress_signals(request_params)
                if signals.get("public_cidrs"):
                    extra["cidrs"] = signals["public_cidrs"]
                set_network("public_exposure", signals.get("public_ingress"))
                set_network("risky_exposure", signals.get("public_ingress_risky_port") or signals.get("public_ingress_all_traffic"))
                if signals.get("public_ingress"):
                    extra["exposure_summary"] = "yes · risky" if signals.get("public_ingress_risky_port") or signals.get("public_ingress_all_traffic") else "yes"
                extra.update(signals)
        if action.startswith("backup."):
            backup_fields = {
                "vault_name": ("backupVaultName", "vaultName"),
                "vault_arn": ("backupVaultArn", "vaultArn"),
                "recovery_point_arn": ("recoveryPointArn",),
                "resource_arn": ("resourceArn",),
                "source_vault_arn": ("sourceBackupVaultArn", "sourceVaultArn"),
                "source_vault_name": ("sourceBackupVaultName", "sourceVaultName"),
                "destination_vault_arn": ("destinationBackupVaultArn", "destinationVaultArn"),
                "job_id": ("copyJobId", "jobId"),
                "plan_name": ("backupPlanName", "planName"),
                "recovery_point_time": ("recoveryPointCreationDate", "creationDate"),
                "retention_days": ("retentionDays",),
            }
            for normalized, provider_keys in backup_fields.items():
                value = next((request_params.get(key) for key in provider_keys if request_params.get(key) is not None), None)
                if value is not None:
                    extra[normalized] = value
            # Backup APIs return some identifiers in responseElements rather
            # than requestParameters. Preserve them for the notification.
            if response:
                for normalized, provider_keys in {
                    "vault_arn": ("backupVaultArn",),
                    "job_id": ("copyJobId", "jobId"),
                }.items():
                    if normalized not in extra:
                        value = next((response.get(key) for key in provider_keys if response.get(key) is not None), None)
                        if value is not None:
                            extra[normalized] = value
            destination = extra.get("destination_vault_arn")
            if destination and isinstance(destination, str):
                parts = destination.split(":")
                if len(parts) > 4:
                    extra.setdefault("destination_region", parts[3])
                    extra.setdefault("destination_account", parts[4])
            if action in ("backup.vault.policy.put", "backup.vault.policy.delete"):
                policy = request_params.get("policy")
                if policy is not None:
                            extra["policy_summary"] = str(policy)[:500]
        if action.startswith("secrets.secret."):
            # Keep lifecycle metadata useful to recipients, but never copy
            # SecretString/SecretBinary or arbitrary provider response data.
            secret_fields = {
                "secret_name": ("name", "secretId"),
                "description": ("description",),
                "kms_key_id": ("kmsKeyId",),
                "version_id": ("versionId",),
                "version_stages": ("versionStages",),
                "rotation_enabled": ("rotationEnabled",),
                "rotation_days": ("rotationRules",),
                "recovery_window_days": ("recoveryWindowInDays",),
                "force_delete": ("forceDeleteWithoutRecovery",),
            }
            for normalized, provider_keys in secret_fields.items():
                value = next((request_params.get(key) for key in provider_keys if request_params.get(key) is not None), None)
                if normalized == "rotation_days" and isinstance(value, dict):
                    value = value.get("automaticallyAfterDays")
                if value is not None and value != "":
                    extra[normalized] = value
            for normalized, provider_keys in {
                "secret_arn": ("ARN", "arn"),
                "secret_name": ("name",),
                "version_id": ("versionId",),
                "version_stages": ("versionStages",),
                "kms_key_id": ("kmsKeyId",),
                "rotation_enabled": ("rotationEnabled",),
                "rotation_days": ("rotationRules",),
            }.items():
                value = next((response.get(key) for key in provider_keys if response.get(key) is not None), None)
                if normalized == "rotation_days" and isinstance(value, dict):
                    value = value.get("automaticallyAfterDays")
                if value is not None and value != "":
                    extra.setdefault(normalized, value)
            if action == "secrets.secret.update":
                extra["change_type"] = "value or metadata updated"
            elif action == "secrets.secret.create":
                extra["change_type"] = "secret created"
            elif action == "secrets.secret.restore":
                extra["change_type"] = "deletion cancelled"
            elif action == "secrets.secret.delete":
                extra["change_type"] = "secret scheduled for deletion"
        if action.startswith("efs."):
            efs_fields = {
                "efs_filesystem_id": ("fileSystemId", "filesystemId"),
                "efs_mount_target_id": ("mountTargetId",),
                "efs_subnet_id": ("subnetId",),
                "efs_availability_zone": ("availabilityZone", "az"),
                "efs_ip_address": ("ipAddress",),
                "efs_security_groups": ("securityGroups",),
                "efs_policy_summary": ("policy", "fileSystemPolicy"),
                "efs_filesystem_name": ("fileSystemName", "name"),
            }
            for normalized, provider_keys in efs_fields.items():
                value = next((request_params.get(key) for key in provider_keys if request_params.get(key) is not None), None)
                if value is not None:
                    if normalized == "efs_policy_summary":
                        value = str(value)[:500]
                    extra[normalized] = value
            if response:
                for normalized, provider_keys in {
                    "efs_mount_target_id": ("mountTargetId",),
                    "efs_filesystem_id": ("fileSystemId", "filesystemId"),
                    "efs_availability_zone": ("availabilityZone", "az"),
                }.items():
                    if normalized not in extra:
                        value = next((response.get(key) for key in provider_keys if response.get(key) is not None), None)
                        if value is not None:
                            extra[normalized] = value
            if action == "efs.filesystem.policy.put" and _policy_doc_is_wildcard(request_params.get("policy") or request_params.get("fileSystemPolicy")):
                extra["efs_policy_wildcard"] = True
        if action.startswith("storage."):
            for normalized, provider_key in {
                "snapshot_id": "snapshotId", "volume_id": "volumeId", "encrypted": "encrypted",
                "kms_key_id": "kmsKeyId", "volume_type": "volumeType", "size_gib": "size",
                "availability_zone": "availabilityZone",
            }.items():
                value = request_params.get(provider_key)
                if value is not None and value != "":
                    extra[normalized] = value
            if action == "storage.snapshot.modify":
                permission = request_params.get("createVolumePermission") or {}
                def permission_items(value: Any) -> list[dict[str, Any]]:
                    value = value.get("items") if isinstance(value, dict) else value
                    if isinstance(value, dict):
                        value = [value]
                    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

                added = permission_items(permission.get("add") if isinstance(permission, dict) else None)
                removed = permission_items(permission.get("remove") if isinstance(permission, dict) else None)
                before = permission_items(permission.get("before") if isinstance(permission, dict) else None)
                current = permission_items(permission.get("current") if isinstance(permission, dict) else None)
                public = any(isinstance(item, dict) and item.get("group") == "all" for item in added)
                accounts = [str(item["userId"]) for item in added if isinstance(item, dict) and item.get("userId") not in (None, "all")]
                removed_accounts = [str(item["userId"]) for item in removed if item.get("userId") not in (None, "all")]
                before_accounts = [str(item["userId"]) for item in before if item.get("userId") not in (None, "all")]
                current_accounts = [str(item["userId"]) for item in current if item.get("userId") not in (None, "all")]
                if removed_accounts:
                    extra["snapshot_removed_accounts"] = removed_accounts
                if any(item.get("group") == "all" for item in removed):
                    extra["snapshot_removed_public"] = True
                if before:
                    extra["snapshot_shared_accounts_before"] = before_accounts
                    extra["snapshot_public_before"] = any(item.get("group") == "all" for item in before)
                    extra["snapshot_share_scope_before"] = (
                        "public and cross-account" if extra["snapshot_public_before"] and before_accounts
                        else "public" if extra["snapshot_public_before"]
                        else "cross-account" if before_accounts else "private"
                    )
                if current:
                    extra["snapshot_shared_accounts_current"] = current_accounts
                    extra["snapshot_public_current"] = any(item.get("group") == "all" for item in current)
                    extra["snapshot_share_scope_current"] = (
                        "public and cross-account" if extra["snapshot_public_current"] and current_accounts
                        else "public" if extra["snapshot_public_current"]
                        else "cross-account" if current_accounts else "private"
                    )
                if public:
                    extra["snapshot_public"] = True
                if accounts:
                    extra["snapshot_shared_accounts"] = accounts
                if public and accounts:
                    extra["snapshot_share_scope"] = "public and cross-account"
                elif public:
                    extra["snapshot_share_scope"] = "public"
                elif accounts:
                    extra["snapshot_share_scope"] = "cross-account"

        if action in ("iam.policy.put_inline", "iam.policy.create_version") and _wildcard_policy(request_params):
            extra["wildcard_policy"] = True

        # Login kind — lets the /iam UI tag rows as IAM user / root / SSO
        # without having to introspect userIdentity again client-side.
        if action == "auth.console.login":
            extra["login_kind"] = "root" if is_root else "iam"
        elif action == "auth.federated.login":
            extra["login_kind"] = "sso"

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
        if action == "storage.snapshot.modify":
            if _snapshot_made_public(request_params):
                extra["snapshot_made_public"] = True
            xac = _snapshot_cross_account_share(request_params)
            if xac:
                extra["snapshot_cross_account_share"] = xac
        if action == "compute.ami.modify":
            if request_params.get("imageId") is not None:
                extra["image_id"] = request_params.get("imageId")
            permissions = request_params.get("launchPermission")
            if isinstance(permissions, dict):
                added = permissions.get("add")
                removed = permissions.get("remove")
                added = added if isinstance(added, list) else ([added] if isinstance(added, dict) else [])
                removed = removed if isinstance(removed, list) else ([removed] if isinstance(removed, dict) else [])
                accounts = [str(item["userId"]) for item in added if isinstance(item, dict) and item.get("userId") is not None]
                if accounts:
                    extra["ami_shared_accounts"] = accounts
                if any(isinstance(item, dict) and item.get("group") == "all" for item in added):
                    extra["ami_public"] = True
                removed_accounts = [str(item["userId"]) for item in removed if isinstance(item, dict) and item.get("userId") is not None]
                if removed_accounts:
                    extra["ami_removed_accounts"] = removed_accounts
            if _ami_made_public(request_params):
                extra["ami_made_public"] = True
            xac = _ami_cross_account_share(request_params)
            if xac:
                extra["ami_cross_account_share"] = xac
        if action == "compute.imds.modify":
            if request_params.get("instanceId") is not None:
                extra["instance_id"] = request_params.get("instanceId")
            metadata = request_params.get("metadataOptions")
            metadata = metadata if isinstance(metadata, dict) else {}
            for source_key, extra_key in (("httpTokens", "http_tokens"), ("httpEndpoint", "http_endpoint"),
                                          ("httpPutResponseHopLimit", "http_put_response_hop_limit"),
                                          ("httpProtocolIpv4", "http_protocol_ipv4"),
                                          ("httpProtocolIpv6", "http_protocol_ipv6"),
                                          ("instanceMetadataTags", "instance_metadata_tags")):
                if metadata.get(source_key) is not None:
                    extra[extra_key] = metadata[source_key]
        if action == "compute.instance.modify":
            if request_params.get("instanceId") is not None:
                extra["instance_id"] = request_params.get("instanceId")
            instance_type = request_params.get("instanceType")
            if isinstance(instance_type, dict):
                instance_type = instance_type.get("value")
            if instance_type is not None:
                extra["instance_type"] = instance_type
            source_dest = request_params.get("sourceDestCheck")
            if isinstance(source_dest, dict):
                source_dest = source_dest.get("value")
            if source_dest is not None:
                extra["source_dest_check"] = source_dest
        if action == "kms.policy.put" and _kms_policy_is_wildcard(request_params):
            extra["kms_wildcard_policy"] = True

        # EFS / AWS Backup / Secrets Manager signals.
        if action == "efs.filesystem.policy.put" and _policy_doc_is_wildcard(request_params.get("policy")):
            extra["efs_policy_wildcard"] = True
        if action == "efs.mount_target.sg.modify":
            sgs = _efs_mount_target_sg_added(request_params)
            if sgs:
                extra["efs_mount_target_sgs"] = sgs
        if action == "backup.vault.policy.put" and _policy_doc_is_wildcard(request_params.get("policy")):
            extra["backup_vault_policy_wildcard"] = True
        if action == "backup.copy_job.start":
            dest_acct = _backup_copy_cross_account(request_params)
            if dest_acct:
                extra["backup_copy_dest_account"] = dest_acct

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
        if action in ("rds.snapshot.modify", "rds.cluster_snapshot.modify"):
            if _rds_snapshot_made_public(request_params):
                extra["rds_snapshot_made_public"] = True
            xac = _rds_snapshot_cross_account_share(request_params)
            if xac:
                extra["rds_snapshot_cross_account_share"] = xac
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

        # Friendly headline for Slack/Discord/etc. Notification templates use
        # `event.extra.message or event.action`, so this is what humans see.
        # Synthesized AFTER all signal flags + the compute.instance.modify
        # override above, so the message reflects the FINAL action + target.
        friendly = _friendly_message(action, extra, request_params, target_id)
        if friendly:
            extra["message"] = friendly

        event_id_src = detail.get("eventID")
        kwargs: dict[str, Any] = {}
        if event_id_src:
            kwargs["event_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudtrail:{event_id_src}"))

        raw_for_event = _redact_secret_payload(raw) if action.startswith("secrets.") else raw
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
            raw=raw_for_event,
            **kwargs,
        )
        return [event]
