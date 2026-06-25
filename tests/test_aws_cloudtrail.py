"""AWS CloudTrail adapter tests + extra.* rule-field access. No AWS/network."""

from blackwatch.modules.aws_cloudtrail import AwsCloudTrailAdapter
from blackwatch.modules.base import IngestContext
from blackwatch.rules.engine import get_field
from blackwatch.event import Event, Source


def _ctx():
    return IngestContext(module="aws.cloudtrail", transport="queue")


def _eb(detail: dict, source="aws.iam", account="123456789012", region="us-east-1") -> dict:
    return {
        "detail-type": "AWS API Call via CloudTrail",
        "source": source,
        "account": account,
        "region": region,
        "time": "2026-05-26T10:00:00Z",
        "detail": detail,
    }


def test_attach_admin_policy():
    ev = AwsCloudTrailAdapter().parse(
        _eb({
            "eventID": "evt-1",
            "eventName": "AttachUserPolicy",
            "eventSource": "iam.amazonaws.com",
            "eventTime": "2026-05-26T10:00:00Z",
            "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::123:user/dave"},
            "sourceIPAddress": "203.0.113.5",
            "requestParameters": {"userName": "dave", "policyArn": "arn:aws:iam::aws:policy/AdministratorAccess"},
        }),
        _ctx(),
    )[0]
    assert ev.action == "iam.policy.attach"
    assert ev.category.value == "iam"
    assert ev.actor.principal == "arn:aws:iam::123:user/dave"
    assert ev.actor.source_ip == "203.0.113.5"
    assert ev.target.id == "arn:aws:iam::aws:policy/AdministratorAccess"
    assert ev.outcome.value == "success"
    # deterministic id from eventID (dedup across SQS redelivery)
    again = AwsCloudTrailAdapter().parse(
        _eb({"eventID": "evt-1", "eventName": "AttachUserPolicy", "eventSource": "iam.amazonaws.com",
             "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::123:user/dave"},
             "requestParameters": {}}),
        _ctx(),
    )[0]
    assert ev.event_id == again.event_id


def test_root_console_login_failure():
    ev = AwsCloudTrailAdapter().parse(
        _eb({
            "eventName": "ConsoleLogin",
            "eventSource": "signin.amazonaws.com",
            "userIdentity": {"type": "Root", "arn": "arn:aws:iam::123:root"},
            "responseElements": {"ConsoleLogin": "Failure"},
            "additionalEventData": {"MFAUsed": "No"},
            "sourceIPAddress": "198.51.100.9",
        }, source="aws.signin"),
        _ctx(),
    )[0]
    assert ev.action == "auth.console.login"
    assert ev.outcome.value == "failure"
    assert ev.actor.is_root is True
    assert ev.extra["mfa_used"] == "No"


def test_wildcard_inline_policy_flagged():
    ev = AwsCloudTrailAdapter().parse(
        _eb({
            "eventName": "PutUserPolicy",
            "eventSource": "iam.amazonaws.com",
            "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::123:user/dave"},
            "requestParameters": {
                "userName": "dave",
                "policyDocument": '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}',
            },
        }),
        _ctx(),
    )[0]
    assert ev.action == "iam.policy.put_inline"
    assert ev.extra.get("wildcard_policy") is True


def test_unmapped_event_falls_back():
    ev = AwsCloudTrailAdapter().parse(
        _eb({"eventName": "GetCallerIdentity", "eventSource": "sts.amazonaws.com",
             "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::123:user/x"}}),
        _ctx(),
    )[0]
    assert ev.action == "aws.sts.getcalleridentity"
    assert ev.category.value == "audit"


def test_non_dict_payload_ignored():
    assert AwsCloudTrailAdapter().parse("not-a-dict", _ctx()) == []


def test_get_field_reaches_into_extra():
    ev = Event(source=Source(module="aws.cloudtrail"), action="auth.console.login",
               extra={"mfa_used": "No"})
    assert get_field(ev, "extra.mfa_used") == "No"
    assert get_field(ev, "extra.missing") is None
