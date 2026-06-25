"""AWS posture adapter + CloudTrail signal detectors + per-check logic."""

import json

from blackwatch.modules.aws_cloudtrail import (
    AwsCloudTrailAdapter,
    _ami_made_public,
    _imds_weakened,
    _kms_policy_is_wildcard,
    _sg_ingress_signals,
    _snapshot_made_public,
)
from blackwatch.modules.aws_posture import AwsPostureAdapter, finding_id
from blackwatch.modules.base import IngestContext


# ---------- SG ingress signal detector --------------------------------------

def test_sg_ingress_signals_risky_port_public():
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 22, "toPort": 22,
        "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]},
    }]}}
    sig = _sg_ingress_signals(rp)
    assert sig.get("public_ingress") is True
    assert sig.get("public_ingress_risky_port") is True
    assert 22 in sig.get("public_ports") or []


def test_sg_ingress_signals_non_web_public_not_flagged_risky():
    """Port 8080 is public but not in the risky-ports list — flagged public
    but NOT public_ingress_risky_port. The s3-style rule layer decides what
    severity to give it."""
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 8080, "toPort": 8080,
        "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]},
    }]}}
    sig = _sg_ingress_signals(rp)
    assert sig.get("public_ingress") is True
    assert "public_ingress_risky_port" not in sig


def test_sg_ingress_signals_web_public_doesnt_flag_risky():
    """Public 80/443 is expected web traffic."""
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 443, "toPort": 443,
        "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]},
    }]}}
    sig = _sg_ingress_signals(rp)
    assert sig.get("public_ingress") is True
    assert "public_ingress_risky_port" not in sig


def test_sg_ingress_signals_private_cidr_not_public():
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 22, "toPort": 22,
        "ipRanges": {"items": [{"cidrIp": "10.0.0.0/8"}]},
    }]}}
    assert _sg_ingress_signals(rp) == {}


def test_sg_ingress_signals_all_traffic_protocol():
    """Protocol -1 = all protocols; public-anywhere = critical 'all traffic'."""
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "-1",
        "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]},
    }]}}
    sig = _sg_ingress_signals(rp)
    assert sig.get("public_ingress_all_traffic") is True


def test_sg_ingress_signals_broad_port_range_treated_as_all_traffic():
    """fromPort=0 + toPort>=1024 publicly = effectively all-traffic public."""
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 0, "toPort": 65535,
        "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]},
    }]}}
    sig = _sg_ingress_signals(rp)
    assert sig.get("public_ingress_all_traffic") is True


def test_sg_ingress_signals_ipv6_world():
    rp = {"ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 5432, "toPort": 5432,
        "ipv6Ranges": {"items": [{"cidrIpv6": "::/0"}]},
    }]}}
    sig = _sg_ingress_signals(rp)
    assert sig.get("public_ingress_risky_port") is True


# ---------- IMDS / snapshot / AMI / KMS detectors ---------------------------

def test_imds_weakened_when_http_tokens_optional():
    assert _imds_weakened({"httpTokens": "optional"})
    assert not _imds_weakened({"httpTokens": "required"})


def test_snapshot_made_public_via_create_volume_permission_add_group_all():
    rp = {"createVolumePermission": {"add": {"items": [{"group": "all"}]}}}
    assert _snapshot_made_public(rp)


def test_snapshot_made_public_via_user_id_all():
    rp = {"createVolumePermission": {"add": {"items": [{"userId": "all"}]}}}
    assert _snapshot_made_public(rp)


def test_snapshot_specific_account_not_flagged_public():
    rp = {"createVolumePermission": {"add": {"items": [{"userId": "111122223333"}]}}}
    assert not _snapshot_made_public(rp)


def test_ami_made_public_via_launch_permission_group_all():
    rp = {"launchPermission": {"add": {"items": [{"group": "all"}]}}}
    assert _ami_made_public(rp)


def test_kms_policy_wildcard_principal_no_condition_is_public():
    doc = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*",
                                      "Action": "kms:*", "Resource": "*"}]})
    assert _kms_policy_is_wildcard({"policy": doc})


def test_kms_policy_wildcard_with_condition_not_flagged():
    """Scoping by aws:PrincipalOrgID or sourceAccount = legitimate."""
    doc = json.dumps({"Statement": [{
        "Effect": "Allow", "Principal": "*", "Action": "kms:Decrypt",
        "Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-xxxx"}},
    }]})
    assert not _kms_policy_is_wildcard({"policy": doc})


# ---------- CloudTrail adapter end-to-end propagation ----------------------

def _ct(event_name: str, request_params: dict, source: str = "ec2.amazonaws.com") -> dict:
    return {
        "eventName": event_name, "eventSource": source,
        "eventTime": "2026-06-05T18:00:00Z", "awsRegion": "us-west-1",
        "recipientAccountId": "111122223333",
        "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/dave"},
        "sourceIPAddress": "203.0.113.5",
        "requestParameters": request_params,
        "eventID": f"evt-{event_name}",
    }


def _ctx():
    return IngestContext(module="aws.cloudtrail", transport="queue")


def test_adapter_normalizes_sg_ingress_with_public_risky_port():
    rp = {"groupId": "sg-abc", "ipPermissions": {"items": [{
        "ipProtocol": "tcp", "fromPort": 22, "toPort": 22,
        "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]},
    }]}}
    e = AwsCloudTrailAdapter().parse(_ct("AuthorizeSecurityGroupIngress", rp), _ctx())[0]
    assert e.action == "network.sg.ingress.add"
    assert e.extra.get("public_ingress") is True
    assert e.extra.get("public_ingress_risky_port") is True


def test_adapter_normalizes_imds_weakening():
    rp = {"instanceId": "i-abc", "httpTokens": "optional"}
    e = AwsCloudTrailAdapter().parse(_ct("ModifyInstanceMetadataOptions", rp), _ctx())[0]
    assert e.action == "compute.imds.modify"
    assert e.extra.get("imdsv1_enabled") is True


def test_adapter_normalizes_snapshot_made_public():
    rp = {"snapshotId": "snap-abc",
          "createVolumePermission": {"add": {"items": [{"group": "all"}]}}}
    e = AwsCloudTrailAdapter().parse(_ct("ModifySnapshotAttribute", rp), _ctx())[0]
    assert e.action == "storage.snapshot.modify"
    assert e.extra.get("snapshot_made_public") is True


def test_adapter_normalizes_kms_policy_wildcard():
    doc = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*",
                                      "Action": "kms:*", "Resource": "*"}]})
    rp = {"keyId": "key-abc", "policy": doc}
    e = AwsCloudTrailAdapter().parse(_ct("PutKeyPolicy", rp, source="kms.amazonaws.com"), _ctx())[0]
    assert e.action == "kms.policy.put"
    assert e.extra.get("kms_wildcard_policy") is True


# ---------- AWS posture adapter (drift report) -----------------------------

def test_finding_id_is_deterministic_per_resource_and_type():
    a = finding_id("111122223333", "sg-abc", "public_ingress_risky_port")
    b = finding_id("111122223333", "sg-abc", "public_ingress_risky_port")
    c = finding_id("111122223333", "sg-xyz", "public_ingress_risky_port")
    assert a == b
    assert a != c


def test_aws_posture_adapter_emits_finding_per_entry_and_scan_completed():
    rpt = {
        "kind": "aws_posture_report",
        "scanned_at": "2026-06-05T18:00:00Z",
        "scanner_version": "1.0",
        "account": "111122223333",
        "checks_run": ["sg_public_ingress", "ec2_imdsv2"],
        "findings": [
            {"resource_id": "sg-abc", "resource_type": "sg",
             "finding_type": "public_ingress_risky_port", "severity": "critical",
             "region": "us-west-1", "evidence": {"port": 22, "cidr": "0.0.0.0/0"}},
            {"resource_id": "i-1234", "resource_type": "ec2_instance",
             "finding_type": "imdsv1_enabled", "severity": "high",
             "region": "us-west-1", "evidence": {"http_tokens": "optional"}},
        ],
        "scan_complete": True,
    }
    events = AwsPostureAdapter().parse(rpt, IngestContext(module="aws.posture", transport="poll"))
    actions = [e.action for e in events]
    assert actions.count("aws.posture.finding") == 2
    assert actions.count("aws.posture.scan.completed") == 1

    findings = [e for e in events if e.action == "aws.posture.finding"]
    by_resource = {f.extra["resource_id"]: f for f in findings}
    sg = by_resource["sg-abc"]
    assert sg.severity.value == "critical"
    assert sg.category.value == "network"
    assert sg.target.type == "aws.sg"
    assert sg.extra["finding_id"] == finding_id("111122223333", "sg-abc",
                                                 "public_ingress_risky_port")

    ec2 = by_resource["i-1234"]
    assert ec2.category.value == "compute"

    sc = next(e for e in events if e.action == "aws.posture.scan.completed")
    assert sg.extra["finding_id"] in sc.extra["finding_ids"]
    assert ec2.extra["finding_id"] in sc.extra["finding_ids"]


def test_aws_posture_adapter_partial_scan_skips_reconciliation():
    """When scan_complete=False, no aws.posture.scan.completed event is emitted —
    so the projection won't mark live findings resolved on a crashed scan."""
    rpt = {
        "kind": "aws_posture_report", "scanned_at": "2026-06-05T18:00:00Z",
        "scanner_version": "1.0", "account": "111122223333",
        "checks_run": ["sg_public_ingress"],
        "findings": [{"resource_id": "sg-x", "resource_type": "sg",
                     "finding_type": "public_ingress_risky_port",
                     "severity": "critical", "region": "us-east-1", "evidence": {}}],
        "scan_complete": False,
    }
    events = AwsPostureAdapter().parse(rpt, IngestContext(module="aws.posture", transport="poll"))
    assert not any(e.action == "aws.posture.scan.completed" for e in events)
    assert any(e.action == "aws.posture.finding" for e in events)


def test_aws_posture_adapter_ignores_malformed_findings():
    rpt = {
        "kind": "aws_posture_report", "scanned_at": "2026-06-05T18:00:00Z",
        "scanner_version": "1.0", "account": "111122223333",
        "checks_run": [],
        "findings": [
            {"resource_id": "sg-ok", "resource_type": "sg",
             "finding_type": "public_ingress_risky_port", "severity": "critical"},
            "not-a-dict",                          # ignored
            {"resource_type": "sg"},               # missing resource_id, ignored
            {"resource_id": "x"},                  # missing resource_type, ignored
        ],
        "scan_complete": True,
    }
    events = AwsPostureAdapter().parse(rpt, IngestContext(module="aws.posture", transport="poll"))
    findings = [e for e in events if e.action == "aws.posture.finding"]
    assert len(findings) == 1


def test_aws_posture_adapter_ignores_non_report():
    out = AwsPostureAdapter().parse({"kind": "something_else"},
                                     IngestContext(module="aws.posture", transport="poll"))
    assert out == []


# ---------- Phase 2b: policy-doc parsers used by IAM-role + KMS-policy checks

from blackwatch.connectors.aws_posture_drift import _policy_doc_has_wildcard_principal


def test_policy_doc_wildcard_principal_string_form():
    """Inline-trust-policy style: Principal: "*"."""
    doc = {"Statement": [{"Effect": "Allow", "Principal": "*",
                          "Action": "sts:AssumeRole"}]}
    assert _policy_doc_has_wildcard_principal(doc)


def test_policy_doc_wildcard_principal_aws_form():
    """Principal: {"AWS": "*"} — the other common shape."""
    doc = {"Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"},
                          "Action": "kms:Decrypt"}]}
    assert _policy_doc_has_wildcard_principal(doc)


def test_policy_doc_wildcard_principal_aws_list_form():
    """Principal: {"AWS": ["*", "arn:..."]} — list-form wildcard."""
    doc = {"Statement": [{"Effect": "Allow",
                          "Principal": {"AWS": ["*", "arn:aws:iam::123:root"]},
                          "Action": "*"}]}
    assert _policy_doc_has_wildcard_principal(doc)


def test_policy_doc_string_input_parses():
    """KMS GetKeyPolicy returns the policy as a JSON STRING — must still parse."""
    doc_str = '{"Statement":[{"Effect":"Allow","Principal":"*","Action":"kms:*"}]}'
    assert _policy_doc_has_wildcard_principal(doc_str)


def test_policy_doc_with_condition_not_flagged():
    """Allow + Principal=* WITH a scoping Condition (org-id, source-account,
    PrincipalOrgID, IP, etc.) is NOT public — those are real legitimate
    patterns and we must not false-positive on them."""
    doc = {"Statement": [{
        "Effect": "Allow", "Principal": "*", "Action": "kms:Decrypt",
        "Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-xxxx"}},
    }]}
    assert not _policy_doc_has_wildcard_principal(doc)


def test_policy_doc_account_root_principal_not_wildcard():
    """Default KMS key policies grant access to `arn:aws:iam::ACCOUNT:root` —
    that's the canonical 'this account can use the key' grant, NOT wildcard.
    Must not be flagged."""
    doc = {"Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
        "Action": "kms:*", "Resource": "*",
    }]}
    assert not _policy_doc_has_wildcard_principal(doc)


def test_policy_doc_deny_wildcard_not_flagged():
    """Effect=Deny with Principal=* is fine — that's a denylist, not a grant."""
    doc = {"Statement": [{"Effect": "Deny", "Principal": "*",
                          "Action": "kms:Decrypt"}]}
    assert not _policy_doc_has_wildcard_principal(doc)


def test_policy_doc_malformed_inputs_return_false():
    assert not _policy_doc_has_wildcard_principal(None)
    assert not _policy_doc_has_wildcard_principal("not-json")
    assert not _policy_doc_has_wildcard_principal({})
    assert not _policy_doc_has_wildcard_principal(42)


# ---------- AwsPostureDriftConfig: defaults for Phase 2b ---------------------

def test_aws_posture_config_defaults_include_phase2b_checks():
    """Defaults should turn ON all Tier-1 checks — operators can disable
    individually, but the safe default is full coverage."""
    from blackwatch.connectors.models import AwsPostureDriftConfig
    cfg = AwsPostureDriftConfig()
    # Phase 2a
    assert cfg.check_sg_public_ingress
    assert cfg.check_ebs_encryption
    assert cfg.check_ebs_snapshot_public
    assert cfg.check_ec2_imdsv2
    assert cfg.check_ami_public
    # Phase 2b — IAM
    assert cfg.check_iam_user_no_mfa
    assert cfg.check_iam_key_age
    assert cfg.check_iam_key_unused
    assert cfg.check_iam_role_wildcard_trust
    # Phase 2b — KMS + CloudTrail
    assert cfg.check_kms_rotation
    assert cfg.check_kms_policy_wildcard
    assert cfg.check_cloudtrail_validation
    # Threshold defaults
    assert cfg.iam_key_max_age_days == 90
    assert cfg.iam_key_unused_threshold_days == 90
