"""S3 adapter + projection helpers + CloudTrail S3 detection signals."""

import json

from blackwatch.modules.aws_cloudtrail import (
    AwsCloudTrailAdapter,
    _acl_grants_public,
    _bpa_weakened,
    _bucket_policy_is_public,
    _logging_disabled,
    _mfa_delete_disabled,
    _versioning_suspended,
)
from blackwatch.modules.aws_s3 import AwsS3Adapter
from blackwatch.modules.base import IngestContext


# ---------- CloudTrail S3 signal detectors --------------------------------------

def test_bucket_policy_with_wildcard_principal_is_public():
    doc = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": "*",
                       "Action": "s3:GetObject", "Resource": "arn:..."}],
    })
    assert _bucket_policy_is_public({"bucketPolicy": doc})


def test_bucket_policy_with_condition_is_not_flagged_public():
    """Operators often allow Principal:* but scope by VPC endpoint / IP /
    aws:SourceIp — we MUST NOT flag those as public, that'd be alert fatigue."""
    doc = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": "*",
                       "Action": "s3:GetObject", "Resource": "arn:...",
                       "Condition": {"IpAddress": {"aws:SourceIp": "203.0.113.0/24"}}}],
    })
    assert not _bucket_policy_is_public({"bucketPolicy": doc})


def test_bucket_policy_aws_wildcard_principal_is_public():
    doc = json.dumps({
        "Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"},
                       "Action": "s3:GetObject", "Resource": "arn:..."}],
    })
    assert _bucket_policy_is_public({"bucketPolicy": doc})


def test_acl_canned_public_read_flagged():
    assert _acl_grants_public({"x-amz-acl": "public-read"})
    assert _acl_grants_public({"x-amz-acl": "public-read-write"})
    assert _acl_grants_public({"x-amz-acl": "authenticated-read"})


def test_acl_explicit_grantee_uri_flagged():
    rp = {"AccessControlPolicy": {"Grants": [{"Grantee": {
        "URI": "http://acs.amazonaws.com/groups/global/AllUsers"}}]}}
    assert _acl_grants_public(rp)


def test_acl_private_canned_not_flagged():
    assert not _acl_grants_public({"x-amz-acl": "private"})


def test_bpa_weakened_when_any_false():
    """All 4 booleans must be true for posture to be 'strong'."""
    rp = {"PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": True, "RestrictPublicBuckets": False}}  # one false
    assert _bpa_weakened(rp)


def test_bpa_not_weakened_when_all_true():
    rp = {"PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": True, "RestrictPublicBuckets": True}}
    assert not _bpa_weakened(rp)


def test_versioning_suspended_detected():
    assert _versioning_suspended({"VersioningConfiguration": {"Status": "Suspended"}})
    assert not _versioning_suspended({"VersioningConfiguration": {"Status": "Enabled"}})


def test_mfa_delete_disabled_detected():
    assert _mfa_delete_disabled({"VersioningConfiguration": {"MfaDelete": "Disabled"}})
    assert not _mfa_delete_disabled({"VersioningConfiguration": {"MfaDelete": "Enabled"}})


def test_logging_disabled_when_target_absent():
    assert _logging_disabled({"BucketLoggingStatus": {}})
    assert not _logging_disabled({"BucketLoggingStatus": {"LoggingEnabled": {"TargetBucket": "logs"}}})


# ---------- CloudTrail adapter end-to-end ---------------------------------------

def _ct(event_name: str, request_params: dict, bucket: str = "patient-data-prod") -> dict:
    """Build a CloudTrail record envelope the adapter consumes."""
    return {
        "eventName": event_name,
        "eventSource": "s3.amazonaws.com",
        "eventTime": "2026-06-05T18:00:00Z",
        "awsRegion": "us-west-1",
        "recipientAccountId": "111122223333",
        "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/dave",
                         "userName": "dave"},
        "sourceIPAddress": "203.0.113.5",
        "requestParameters": {"bucketName": bucket, **request_params},
        "eventID": f"evt-{event_name}-{bucket}",
    }


def _ctx():
    return IngestContext(module="aws.cloudtrail", transport="queue")


def test_adapter_normalizes_putbucketacl_with_public_acl():
    """Adapter must emit action=s3.bucket.acl.put AND set extra.public_acl=True
    when the grant goes to AllUsers — rules in s3.yaml match on that signal."""
    ev = _ct("PutBucketAcl", {"x-amz-acl": "public-read"})
    events = AwsCloudTrailAdapter().parse(ev, _ctx())
    e = events[0]
    assert e.action == "s3.bucket.acl.put"
    assert e.extra.get("public_acl") is True
    assert e.target.id == "patient-data-prod"
    assert e.target.type == "aws.s3"


def test_adapter_normalizes_putbucketacl_without_public_acl():
    ev = _ct("PutBucketAcl", {"x-amz-acl": "private"})
    e = AwsCloudTrailAdapter().parse(ev, _ctx())[0]
    assert e.action == "s3.bucket.acl.put"
    assert "public_acl" not in e.extra


def test_adapter_normalizes_putbucketpolicy_with_wildcard_no_condition():
    doc = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*",
                                      "Action": "s3:*", "Resource": "arn:..."}]})
    e = AwsCloudTrailAdapter().parse(_ct("PutBucketPolicy", {"bucketPolicy": doc}), _ctx())[0]
    assert e.action == "s3.bucket.policy.put"
    assert e.extra.get("public_policy") is True


def test_adapter_normalizes_putbucketpolicy_scoped_by_condition_not_flagged():
    doc = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*",
                                      "Action": "s3:GetObject", "Resource": "arn:...",
                                      "Condition": {"StringEquals": {"aws:SourceVpce": "vpce-x"}}}]})
    e = AwsCloudTrailAdapter().parse(_ct("PutBucketPolicy", {"bucketPolicy": doc}), _ctx())[0]
    assert e.action == "s3.bucket.policy.put"
    assert "public_policy" not in e.extra


def test_adapter_normalizes_bpa_weakened():
    rp = {"PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": False, "RestrictPublicBuckets": True}}
    e = AwsCloudTrailAdapter().parse(_ct("PutPublicAccessBlock", rp), _ctx())[0]
    assert e.action == "s3.bucket.bpa.put"
    assert e.extra.get("bpa_weakened") is True


def test_adapter_normalizes_versioning_suspended():
    rp = {"VersioningConfiguration": {"Status": "Suspended"}}
    e = AwsCloudTrailAdapter().parse(_ct("PutBucketVersioning", rp), _ctx())[0]
    assert e.action == "s3.bucket.versioning.put"
    assert e.extra.get("versioning_suspended") is True


def test_adapter_normalizes_bucket_delete():
    e = AwsCloudTrailAdapter().parse(_ct("DeleteBucket", {}), _ctx())[0]
    assert e.action == "s3.bucket.delete"
    assert e.target.id == "patient-data-prod"


# ---------- S3 inventory adapter (snapshot events) -----------------------------

def test_s3_adapter_emits_snapshot_per_bucket_plus_scan_completed():
    rpt = {
        "kind": "s3_bucket_snapshot",
        "scanned_at": "2026-06-05T18:00:00Z",
        "scanner_version": "1.0",
        "account": "111122223333",
        "buckets": [
            {"name": "patient-data-prod", "region": "us-west-1",
             "public": False, "encryption": "AES256", "versioning": "Enabled",
             "block_public_access": {"block_public_acls": True}},
            {"name": "marketing-public", "region": "us-east-1",
             "public": True, "public_reasons": ["acl_grants_public"],
             "encryption": "none", "versioning": "Disabled"},
        ],
        "scan_complete": True,
    }
    events = AwsS3Adapter().parse(rpt, IngestContext(module="aws.s3", transport="poll"))
    actions = [e.action for e in events]
    assert actions.count("s3.bucket.snapshot") == 2
    assert actions.count("s3.scan.completed") == 1

    by_name = {e.extra["bucket_name"]: e for e in events if e.action == "s3.bucket.snapshot"}
    assert by_name["marketing-public"].extra["public"] is True
    assert by_name["marketing-public"].extra["public_reasons"] == ["acl_grants_public"]
    assert by_name["patient-data-prod"].extra["encryption"] == "AES256"

    sc = next(e for e in events if e.action == "s3.scan.completed")
    assert sc.extra["bucket_names"] == ["patient-data-prod", "marketing-public"]


def test_s3_adapter_skips_partial_scan_reconciliation():
    """When scan_complete=False, NO s3.scan.completed event fires — so the
    projection won't delete buckets that just happen to be missing because the
    scan crashed."""
    rpt = {
        "kind": "s3_bucket_snapshot", "scanned_at": "2026-06-05T18:00:00Z",
        "scanner_version": "1.0", "account": "111122223333",
        "buckets": [{"name": "only-one-i-got-to", "public": False,
                     "encryption": "AES256", "versioning": "Enabled"}],
        "scan_complete": False,
    }
    events = AwsS3Adapter().parse(rpt, IngestContext(module="aws.s3", transport="poll"))
    assert not any(e.action == "s3.scan.completed" for e in events)
    assert any(e.action == "s3.bucket.snapshot" for e in events)


def test_s3_adapter_ignores_non_snapshot_kind():
    assert AwsS3Adapter().parse({"kind": "something_else"},
                                 IngestContext(module="aws.s3", transport="poll")) == []
