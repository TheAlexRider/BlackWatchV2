#!/usr/bin/env python3
"""End-to-end /iam test-drive — fires real AWS calls so real CloudTrail
events flow through your CloudTrail → EventBridge → Lambda → SQS → BlackWatch
pipeline. Then cleans every resource it created.

What it does (default plan):

    IAM changes
      - create user             bw-testdrive-user-<rand>
      - create login profile    (so iam.login_profile.create fires)
      - create access key       (iam.access_key.create)
      - attach managed policy   (iam.policy.attach — ReadOnlyAccess)
      - create role             bw-testdrive-role-<rand>

    Security group changes
      - create SG               bw-testdrive-sg-<rand>
      - authorize ingress       (TCP/22 from 0.0.0.0/0 — your public-ingress
                                 detector should fire on this)

    Storage exposure (safe)
      - create S3 bucket        bw-testdrive-bpa-<rand>
      - put bucket BPA          (fires s3.bucket.bpa.put — does NOT expose
                                 anything; we set all blocks ON)

    AssumeRole
      - assume the role we just created (fires auth.assume_role)

    KMS (opt-in with --include-kms):
      - create CMK              (cost: ~$0.25 during the 7-day pending window)
      - put key policy w/ wildcard
      - disable key rotation
      - schedule key deletion (7-day pending)

What it does NOT do:
  - Anything destructive to existing resources.
  - Public-share a snapshot or AMI (those are reversible but real exposure
    while open; use --include-snapshot / --include-ami if you want them).
  - Touch CloudTrail itself.
  - Touch your host posture state (those events come from the on-host agent,
    not CloudTrail — there's no AWS call that fires them).

Idempotency / safety:
  - Every resource gets tagged Key=blackwatch-test-drive, Value=true.
  - Names share a unique suffix per run so concurrent runs don't collide.
  - --cleanup-only finds and removes every tagged test-drive resource it can
    see, regardless of which run created it. Safe to run after Ctrl+C.

Usage:
    python scripts/aws_iam_test_drive.py
    python scripts/aws_iam_test_drive.py --profile prod --region us-west-1
    python scripts/aws_iam_test_drive.py --include-kms
    python scripts/aws_iam_test_drive.py --cleanup-only
    python scripts/aws_iam_test_drive.py -y           # skip the confirm prompt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    sys.stderr.write(
        "boto3 is required. pip install boto3, or run inside the app container:\n"
        "    docker compose exec app python /app/scripts/aws_iam_test_drive.py\n"
    )
    sys.exit(1)


TAG_KEY = "blackwatch-test-drive"
TAG_VALUE = "true"
NAME_PREFIX = "bw-testdrive"


# ---------- Pretty output ----------------------------------------------------


_step = 0
_total = 0


def banner(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title) - 4))


def step(label: str) -> None:
    global _step
    _step += 1
    width = max(2, len(str(_total)))
    print(f"  [{_step:>{width}}/{_total}] {label:<45s}", end="", flush=True)


def ok(detail: str = "") -> None:
    print(f" ✓ {detail}")


def skip(reason: str) -> None:
    print(f" - skipped ({reason})")


def fail(exc: Exception) -> None:
    print(f" ✗ {type(exc).__name__}: {exc}")


# ---------- AWS clients ------------------------------------------------------


def make_session(profile: str | None, region: str) -> boto3.Session:
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


# ---------- Plan + confirm ---------------------------------------------------


def print_plan(include_kms: bool, include_snapshot: bool, include_ami: bool,
               account: str, region: str) -> None:
    print(f"Account: {account}    Region: {region}")
    print(f"Tag:     {TAG_KEY}={TAG_VALUE}    Name prefix: {NAME_PREFIX}-*")
    print()
    print("Will fire these CloudTrail events:")
    print("  iam.user.create / iam.login_profile.create / iam.access_key.create")
    print("  iam.policy.attach / iam.role.create")
    print("  network.sg.create / network.sg.ingress.add (public-ingress + risky-port flags)")
    print("  s3.bucket.bpa.put (no actual exposure)")
    print("  auth.assume_role")
    if include_kms:
        print("  kms.policy.put (wildcard principal flag) / kms.rotation.disable / kms.key.delete_scheduled")
    if include_snapshot:
        print("  storage.snapshot.modify (snapshot_made_public=True) ⚠️ briefly public")
    if include_ami:
        print("  compute.ami.modify (ami_made_public=True) ⚠️ briefly public")
    print()
    print("Will NOT touch any existing resource. Cleanup removes everything we create.")
    if include_kms:
        print()
        print("⚠️  KMS: a CMK will be scheduled for deletion with a 7-day pending")
        print("    window. Cost: ~$0.25 prorated. Cancel anytime via AWS console.")


def confirm(prompt: str) -> bool:
    try:
        a = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return a in ("y", "yes")


# ---------- Create phase -----------------------------------------------------


def do_iam(session: boto3.Session, suffix: str) -> dict[str, str]:
    """Returns dict of created resource names so AssumeRole + cleanup can find them."""
    iam = session.client("iam")
    out: dict[str, str] = {}

    user = f"{NAME_PREFIX}-user-{suffix}"
    role = f"{NAME_PREFIX}-role-{suffix}"

    step(f"iam.user.create  → {user}")
    try:
        iam.create_user(UserName=user, Tags=[{"Key": TAG_KEY, "Value": TAG_VALUE}])
        out["user"] = user
        ok()
    except Exception as exc:
        fail(exc)

    if "user" in out:
        step("iam.login_profile.create")
        try:
            # Random throwaway password — user has no console access path enabled
            # (no MFA, no recovery email). Login profile gets deleted in cleanup.
            iam.create_login_profile(
                UserName=out["user"],
                Password=f"BWTestDrive!{uuid.uuid4().hex[:8]}Aa1",
                PasswordResetRequired=True,
            )
            out["login_profile"] = out["user"]
            ok()
        except Exception as exc:
            fail(exc)

        step("iam.access_key.create")
        try:
            resp = iam.create_access_key(UserName=out["user"])
            out["access_key_id"] = resp["AccessKey"]["AccessKeyId"]
            ok(f"key={out['access_key_id']}")
        except Exception as exc:
            fail(exc)

        step("iam.policy.attach  → ReadOnlyAccess")
        try:
            iam.attach_user_policy(
                UserName=out["user"],
                PolicyArn="arn:aws:iam::aws:policy/ReadOnlyAccess",
            )
            out["policy_arn"] = "arn:aws:iam::aws:policy/ReadOnlyAccess"
            ok()
        except Exception as exc:
            fail(exc)

    # Role we can AssumeRole into — trust policy allows the current caller.
    sts = session.client("sts")
    caller = sts.get_caller_identity()
    step(f"iam.role.create  → {role}")
    try:
        trust = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"AWS": caller["Arn"]},
                "Action": "sts:AssumeRole",
            }],
        }
        iam.create_role(
            RoleName=role,
            AssumeRolePolicyDocument=json.dumps(trust),
            Tags=[{"Key": TAG_KEY, "Value": TAG_VALUE}],
        )
        out["role"] = role
        ok()
    except Exception as exc:
        fail(exc)

    return out


def do_sg(session: boto3.Session, suffix: str) -> dict[str, str]:
    ec2 = session.client("ec2")
    out: dict[str, str] = {}
    sg_name = f"{NAME_PREFIX}-sg-{suffix}"

    step(f"network.sg.create  → {sg_name}")
    try:
        # Use the default VPC. If you don't have one, the SG won't create —
        # that's not common but we surface the real error.
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
        if not vpcs["Vpcs"]:
            # Fall back to ANY VPC.
            vpcs = ec2.describe_vpcs()
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        resp = ec2.create_security_group(
            GroupName=sg_name,
            Description="BlackWatch test-drive (auto-cleanup)",
            VpcId=vpc_id,
            TagSpecifications=[{
                "ResourceType": "security-group",
                "Tags": [{"Key": TAG_KEY, "Value": TAG_VALUE}],
            }],
        )
        out["sg_id"] = resp["GroupId"]
        ok(out["sg_id"])
    except Exception as exc:
        fail(exc)
        return out

    step("network.sg.ingress.add  → 0.0.0.0/0:22 (public + risky-port)")
    try:
        ec2.authorize_security_group_ingress(
            GroupId=out["sg_id"],
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": 22, "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "BW test"}],
            }],
        )
        ok()
    except Exception as exc:
        fail(exc)

    return out


def do_s3(session: boto3.Session, suffix: str) -> dict[str, str]:
    s3 = session.client("s3")
    out: dict[str, str] = {}
    # S3 bucket names are global — include account + suffix to avoid clashes.
    sts = session.client("sts")
    acct = sts.get_caller_identity()["Account"]
    bucket = f"{NAME_PREFIX}-bpa-{acct}-{suffix}".lower()
    region = session.region_name or "us-east-1"

    step(f"s3 bucket create  → {bucket}")
    try:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
        out["bucket"] = bucket
        # Tag the bucket so cleanup finds it.
        s3.put_bucket_tagging(
            Bucket=bucket,
            Tagging={"TagSet": [{"Key": TAG_KEY, "Value": TAG_VALUE}]},
        )
        ok()
    except Exception as exc:
        fail(exc)
        return out

    step("s3.bucket.bpa.put  → all blocks ON (no exposure)")
    try:
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        ok()
    except Exception as exc:
        fail(exc)

    return out


def do_assume_role(session: boto3.Session, role_name: str | None) -> None:
    if not role_name:
        step("auth.assume_role")
        skip("role wasn't created")
        return

    sts = session.client("sts")
    acct = sts.get_caller_identity()["Account"]
    arn = f"arn:aws:iam::{acct}:role/{role_name}"

    step(f"auth.assume_role  → {role_name}")
    # IAM trust policies take a few seconds to propagate after CreateRole.
    # Retry briefly so we don't fail spuriously on race.
    last_exc: Exception | None = None
    for _ in range(6):
        try:
            sts.assume_role(RoleArn=arn, RoleSessionName="bw-test-drive")
            ok()
            return
        except ClientError as exc:
            last_exc = exc
            time.sleep(5)
    fail(last_exc or RuntimeError("AssumeRole retries exhausted"))


def do_kms(session: boto3.Session, suffix: str) -> dict[str, str]:
    kms = session.client("kms")
    out: dict[str, str] = {}

    step(f"kms.key.create  → {NAME_PREFIX}-{suffix}")
    try:
        resp = kms.create_key(
            Description=f"BlackWatch test-drive {suffix} (auto-cleanup)",
            Tags=[{"TagKey": TAG_KEY, "TagValue": TAG_VALUE}],
        )
        out["key_id"] = resp["KeyMetadata"]["KeyId"]
        ok(out["key_id"])
    except Exception as exc:
        fail(exc)
        return out

    sts = session.client("sts")
    acct = sts.get_caller_identity()["Account"]

    step("kms.policy.put  → wildcard principal (flagged)")
    try:
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {  # Keep admin on the root user so we can still delete the key.
                    "Sid": "RootAdmin",
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{acct}:root"},
                    "Action": "kms:*",
                    "Resource": "*",
                },
                {  # The flagged statement.
                    "Sid": "TestDriveWildcard",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "kms:Describe*",
                    "Resource": "*",
                },
            ],
        }
        kms.put_key_policy(KeyId=out["key_id"], PolicyName="default",
                           Policy=json.dumps(policy))
        ok()
    except Exception as exc:
        fail(exc)

    step("kms.rotation.disable")
    try:
        kms.disable_key_rotation(KeyId=out["key_id"])
        ok()
    except Exception as exc:
        # disable_key_rotation fails on KMS keys that don't support rotation
        # (already disabled, asymmetric, etc.) — non-fatal.
        fail(exc)

    step("kms.key.delete_scheduled  (7-day pending)")
    try:
        kms.schedule_key_deletion(KeyId=out["key_id"], PendingWindowInDays=7)
        ok()
    except Exception as exc:
        fail(exc)

    return out


def do_snapshot_public(session: boto3.Session, snapshot_id: str) -> None:
    """Briefly make a snapshot public. Cleanup reverts. ONLY runs with --include-snapshot."""
    ec2 = session.client("ec2")
    step(f"storage.snapshot.modify  → {snapshot_id} (PUBLIC)")
    try:
        ec2.modify_snapshot_attribute(
            SnapshotId=snapshot_id,
            Attribute="createVolumePermission",
            OperationType="add",
            GroupNames=["all"],
        )
        ok()
    except Exception as exc:
        fail(exc)


def do_ami_public(session: boto3.Session, ami_id: str) -> None:
    """Briefly make an AMI public. Cleanup reverts. ONLY runs with --include-ami."""
    ec2 = session.client("ec2")
    step(f"compute.ami.modify  → {ami_id} (PUBLIC)")
    try:
        ec2.modify_image_attribute(
            ImageId=ami_id,
            LaunchPermission={"Add": [{"Group": "all"}]},
        )
        ok()
    except Exception as exc:
        fail(exc)


# ---------- Cleanup ----------------------------------------------------------


def cleanup_iam(session: boto3.Session) -> None:
    iam = session.client("iam")

    # Find tagged users + roles via list_users/list_roles + per-resource tags
    # (IAM has no global GetResourcesByTagAPI for users/roles; we scan +
    # filter by tag key).
    banner("IAM cleanup")

    # Users — must detach policies, delete access keys, delete login profile first.
    try:
        users = iam.list_users().get("Users", [])
    except Exception as exc:
        print(f"  list_users failed: {exc}")
        users = []
    for u in users:
        name = u["UserName"]
        if not name.startswith(f"{NAME_PREFIX}-user-"):
            continue
        # Confirm tag (so we don't nuke a similarly-named real user).
        tags = iam.list_user_tags(UserName=name).get("Tags", [])
        if not any(t["Key"] == TAG_KEY and t["Value"] == TAG_VALUE for t in tags):
            continue
        print(f"  deleting user {name}")
        # detach policies
        for p in iam.list_attached_user_policies(UserName=name).get("AttachedPolicies", []):
            _safe(lambda: iam.detach_user_policy(UserName=name, PolicyArn=p["PolicyArn"]))
        # delete access keys
        for k in iam.list_access_keys(UserName=name).get("AccessKeyMetadata", []):
            _safe(lambda: iam.delete_access_key(UserName=name, AccessKeyId=k["AccessKeyId"]))
        # delete login profile
        _safe(lambda: iam.delete_login_profile(UserName=name),
              swallow=("NoSuchEntity",))
        _safe(lambda: iam.delete_user(UserName=name))

    # Roles — detach policies first.
    try:
        roles = iam.list_roles().get("Roles", [])
    except Exception as exc:
        print(f"  list_roles failed: {exc}")
        roles = []
    for r in roles:
        name = r["RoleName"]
        if not name.startswith(f"{NAME_PREFIX}-role-"):
            continue
        try:
            tags = iam.list_role_tags(RoleName=name).get("Tags", [])
        except ClientError:
            tags = []
        if not any(t["Key"] == TAG_KEY and t["Value"] == TAG_VALUE for t in tags):
            continue
        print(f"  deleting role {name}")
        for p in iam.list_attached_role_policies(RoleName=name).get("AttachedPolicies", []):
            _safe(lambda: iam.detach_role_policy(RoleName=name, PolicyArn=p["PolicyArn"]))
        _safe(lambda: iam.delete_role(RoleName=name))


def cleanup_sg(session: boto3.Session) -> None:
    ec2 = session.client("ec2")
    banner("Security group cleanup")
    sgs = ec2.describe_security_groups(
        Filters=[{"Name": f"tag:{TAG_KEY}", "Values": [TAG_VALUE]}]
    ).get("SecurityGroups", [])
    for sg in sgs:
        print(f"  deleting sg {sg['GroupId']} ({sg['GroupName']})")
        _safe(lambda: ec2.delete_security_group(GroupId=sg["GroupId"]))


def cleanup_s3(session: boto3.Session) -> None:
    s3 = session.client("s3")
    banner("S3 cleanup")
    try:
        buckets = s3.list_buckets().get("Buckets", [])
    except Exception as exc:
        print(f"  list_buckets failed: {exc}")
        return
    for b in buckets:
        name = b["Name"]
        if not name.startswith(f"{NAME_PREFIX}-bpa-"):
            continue
        try:
            tags = s3.get_bucket_tagging(Bucket=name).get("TagSet", [])
        except ClientError:
            tags = []
        if not any(t["Key"] == TAG_KEY and t["Value"] == TAG_VALUE for t in tags):
            continue
        print(f"  deleting bucket {name}")
        _safe(lambda: s3.delete_bucket(Bucket=name))


def cleanup_kms(session: boto3.Session) -> None:
    """KMS keys go into a pending-deletion window; we move any already-tagged
    key into that pending state if not there yet. Can't actually delete the
    key sooner than the pending window, but it'll auto-delete and cost nothing
    once it does."""
    kms = session.client("kms")
    banner("KMS cleanup (schedules pending deletion)")
    try:
        keys = kms.list_keys().get("Keys", [])
    except Exception as exc:
        print(f"  list_keys failed: {exc}")
        return
    for k in keys:
        key_id = k["KeyId"]
        # tags
        try:
            tags = kms.list_resource_tags(KeyId=key_id).get("Tags", [])
        except ClientError:
            continue
        if not any(t["TagKey"] == TAG_KEY and t["TagValue"] == TAG_VALUE for t in tags):
            continue
        # state
        try:
            meta = kms.describe_key(KeyId=key_id)["KeyMetadata"]
        except ClientError:
            continue
        if meta.get("KeyState") == "PendingDeletion":
            print(f"  key {key_id} already pending deletion — leaving it")
            continue
        print(f"  scheduling deletion of key {key_id}")
        _safe(lambda: kms.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=7))


def cleanup_snapshot_public(session: boto3.Session, snapshot_id: str) -> None:
    ec2 = session.client("ec2")
    banner("Snapshot public-share revert")
    print(f"  un-sharing snapshot {snapshot_id}")
    _safe(lambda: ec2.modify_snapshot_attribute(
        SnapshotId=snapshot_id, Attribute="createVolumePermission",
        OperationType="remove", GroupNames=["all"],
    ))


def cleanup_ami_public(session: boto3.Session, ami_id: str) -> None:
    ec2 = session.client("ec2")
    banner("AMI public revert")
    print(f"  un-sharing AMI {ami_id}")
    _safe(lambda: ec2.modify_image_attribute(
        ImageId=ami_id, LaunchPermission={"Remove": [{"Group": "all"}]},
    ))


def _safe(call, swallow: tuple[str, ...] = ()) -> None:
    """Run a no-arg call; swallow well-understood errors, surface unexpected ones."""
    try:
        call()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in swallow:
            return
        print(f"    ! {code}: {exc.response.get('Error', {}).get('Message', exc)}")
    except Exception as exc:
        print(f"    ! {type(exc).__name__}: {exc}")


# ---------- Main -------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Real-AWS /iam test-drive.")
    p.add_argument("--profile", default=None, help="AWS profile (default: env / default)")
    p.add_argument("--region", default="us-west-1",
                   help="AWS region (default us-west-1 — your CloudTrail region)")
    p.add_argument("--include-kms", action="store_true",
                   help="Also fire KMS events (creates a CMK, ~$0.25 7-day window)")
    p.add_argument("--include-snapshot", metavar="snap-XXX",
                   help="Briefly share an existing snapshot publicly (reverted on cleanup)")
    p.add_argument("--include-ami", metavar="ami-XXX",
                   help="Briefly share an existing AMI publicly (reverted on cleanup)")
    p.add_argument("--cleanup-only", action="store_true",
                   help="Skip create; delete any leftover test-drive resources")
    p.add_argument("-y", "--yes", action="store_true", help="Skip the confirm prompt")
    args = p.parse_args()

    session = make_session(args.profile, args.region)
    sts = session.client("sts")
    try:
        ident = sts.get_caller_identity()
    except Exception as exc:
        print(f"AWS auth failed: {exc}", file=sys.stderr)
        return 1

    if args.cleanup_only:
        print(f"Cleanup mode — account {ident['Account']} region {args.region}")
        cleanup_iam(session)
        cleanup_sg(session)
        cleanup_s3(session)
        cleanup_kms(session)
        print("\ndone.")
        return 0

    print_plan(args.include_kms, bool(args.include_snapshot), bool(args.include_ami),
               ident["Account"], args.region)
    if not args.yes and not confirm("\nProceed?"):
        print("aborted.")
        return 0

    suffix = uuid.uuid4().hex[:6]
    print(f"\nrun suffix: {suffix}")

    # Tally the planned steps so the [N/M] counter is honest.
    global _total
    _total = 5  # iam: user, login_profile, access_key, policy.attach, role.create
    _total += 2  # sg: create, ingress
    _total += 2  # s3: bucket create, bpa.put
    _total += 1  # assume_role
    if args.include_kms:
        _total += 4
    if args.include_snapshot:
        _total += 1
    if args.include_ami:
        _total += 1

    banner("IAM")
    iam_out = do_iam(session, suffix)

    banner("Security group")
    do_sg(session, suffix)

    banner("S3 / storage exposure (safe)")
    do_s3(session, suffix)

    banner("AssumeRole")
    do_assume_role(session, iam_out.get("role"))

    if args.include_kms:
        banner("KMS")
        do_kms(session, suffix)

    if args.include_snapshot:
        banner("Snapshot public-share")
        do_snapshot_public(session, args.include_snapshot)

    if args.include_ami:
        banner("AMI public-share")
        do_ami_public(session, args.include_ami)

    banner("Done — waiting for CloudTrail to propagate")
    print(
        "CloudTrail typically lands events in your S3 bucket within 5–15 minutes.\n"
        "Your EventBridge → Lambda → SQS → BlackWatch pipeline runs as fast as\n"
        "the SQS connector polls. Refresh /iam — sections should populate one by\n"
        "one as events arrive. Counter cells at the top will tick up.\n"
    )
    print("Cleanup options:")
    print("  - Press Enter NOW to clean up immediately (events may keep landing")
    print("    in CloudTrail after cleanup — that's fine, they still show on /iam).")
    print("  - Or Ctrl+C to leave resources in place and clean up later with:")
    print(f"      python {sys.argv[0]} --cleanup-only --region {args.region}"
          + (f" --profile {args.profile}" if args.profile else ""))

    try:
        input("\nPress Enter to clean up now... ")
    except (KeyboardInterrupt, EOFError):
        print("\nleaving resources in place. cleanup later with --cleanup-only.")
        return 0

    cleanup_iam(session)
    cleanup_sg(session)
    cleanup_s3(session)
    if args.include_kms:
        cleanup_kms(session)
    if args.include_snapshot:
        cleanup_snapshot_public(session, args.include_snapshot)
    if args.include_ami:
        cleanup_ami_public(session, args.include_ami)

    print("\ncleanup done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
