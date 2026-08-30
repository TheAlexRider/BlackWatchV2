from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Severity, Source, Target
from blackwatch.modules.aws_cloudtrail import AwsCloudTrailAdapter, _ACTION_MAP
from blackwatch.modules.base import IngestContext
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, normalize_profile


COMPUTE_EVENTS = {
    "compute.imds.modify",
    "compute.ami.modify",
    "compute.instance.modify",
}


def _event(action, **extra):
    return Event(
        source=Source(module="aws.cloudtrail", vendor="aws", account="111111111111", region="us-east-1"),
        category=Category.compute,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        severity=Severity.high,
        actor=Actor(principal="arn:aws:iam::111111111111:user/operator", source_ip="198.51.100.20"),
        target=Target(id=extra.pop("target_id", "i-0123456789abcdef0"), type="aws.ec2"),
        extra=extra,
    )


def _cloudtrail(event_name, request):
    return {
        "eventName": event_name,
        "eventSource": "ec2.amazonaws.com",
        "eventTime": "2026-08-29T10:00:00Z",
        "awsRegion": "us-east-1",
        "sourceIPAddress": "198.51.100.20",
        "recipientAccountId": "111111111111",
        "userIdentity": {"type": "IAMUser", "userName": "operator", "arn": "arn:aws:iam::111111111111:user/operator"},
        "requestParameters": request,
        "responseElements": {},
        "eventID": f"compute-{event_name}",
    }


class Bw029ComputeNotificationTests(unittest.TestCase):
    def test_all_emitted_compute_actions_are_cataloged(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.compute")
        catalog_events = {item["key"] for item in module["events"]}
        producer_events = {action for action, category in _ACTION_MAP.values() if category is Category.compute}
        self.assertEqual(producer_events, catalog_events | set(module.get("producer_event_inventory") or {}))
        self.assertEqual(catalog_events, COMPUTE_EVENTS)
        self.assertEqual(module["content_gap_count"], 0)

    def test_cloudtrail_normalizes_imds_metadata_without_inventing_values(self):
        event = AwsCloudTrailAdapter().parse(_cloudtrail("ModifyInstanceMetadataOptions", {
            "instanceId": "i-0123456789abcdef0",
            "metadataOptions": {"httpTokens": "required", "httpEndpoint": "enabled", "httpPutResponseHopLimit": 2},
        }), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(event.action, "compute.imds.modify")
        self.assertEqual(event.extra["instance_id"], "i-0123456789abcdef0")
        self.assertEqual(event.extra["http_tokens"], "required")
        self.assertEqual(event.extra["http_endpoint"], "enabled")
        self.assertEqual(event.extra["http_put_response_hop_limit"], 2)
        self.assertNotIn("public", event.extra)
        self.assertNotIn("None", repr(event.extra))

    def test_cloudtrail_normalizes_ami_permissions_and_instance_changes(self):
        ami = AwsCloudTrailAdapter().parse(_cloudtrail("ModifyImageAttribute", {
            "imageId": "ami-0123",
            "launchPermission": {"add": [{"userId": "222222222222"}, {"group": "all"}]},
        }), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(ami.extra["image_id"], "ami-0123")
        self.assertEqual(ami.extra["ami_shared_accounts"], ["222222222222"])
        self.assertTrue(ami.extra["ami_public"])

        instance = AwsCloudTrailAdapter().parse(_cloudtrail("ModifyInstanceAttribute", {
            "instanceId": "i-0123456789abcdef0",
            "instanceType": {"value": "m7g.large"},
            "sourceDestCheck": {"value": False},
        }), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(instance.action, "compute.instance.modify")
        self.assertEqual(instance.extra["instance_id"], "i-0123456789abcdef0")
        self.assertEqual(instance.extra["instance_type"], "m7g.large")
        self.assertFalse(instance.extra["source_dest_check"])

    def test_complete_and_partial_email_goldens_are_event_specific(self):
        fixtures = {
            "compute.imds.modify": {"instance_id": "i-0123", "http_tokens": "optional", "http_endpoint": "enabled", "imdsv1_enabled": True},
            "compute.ami.modify": {"image_id": "ami-0123", "ami_public": True, "ami_shared_accounts": ["222222222222"]},
            "compute.instance.modify": {"instance_id": "i-0123", "instance_type": "m7g.large", "source_dest_check": False},
        }
        expected = {
            "compute.imds.modify": """EC2 metadata protection changed · i-0123
What happened: The instance metadata service configuration changed.
Facts: Instance: i-0123
IMDS tokens: optional
IMDS endpoint: enabled
IMDSv1: enabled
Account: 111111111111
Region: us-east-1
Actor: arn:aws:iam::111111111111:user/operator
When: 2026-08-29T10:00:00Z
Decision: Confirm the metadata setting matches the approved instance-hardening baseline; treat IMDSv1 availability as a credential-theft risk until explained.
Next steps: Verify the instance owner and change ticket; require IMDSv2 where approved; review recent instance-role use and investigate unexpected metadata access.
Why it matters: Metadata settings control whether workloads can reach instance credentials and other metadata.
Evidence: CloudTrail supplied the instance and metadata-option values shown above; no credential access is inferred.
Monitoring: AWS CloudTrail EC2 ModifyInstanceMetadataOptions events.
Impact: The instance credential-access boundary changed; compromise or impact is not established by this event alone.
Recovery: No automatic recovery is claimed; manual resolution requires the approved metadata baseline and review of recent role-credential activity.""",
            "compute.ami.modify": """AMI exposure changed · ami-0123
What happened: An EC2 image launch-permission or visibility setting changed.
Facts: AMI: ami-0123
Public visibility: enabled
Shared accounts: 222222222222
Account: 111111111111
Region: us-east-1
Actor: arn:aws:iam::111111111111:user/operator
When: 2026-08-29T10:00:00Z
Decision: Confirm the image exposure is intentional and that the image contains no credentials or sensitive data; public sharing is high risk until proven approved.
Next steps: Review the image contents and owner; compare the permission change with the release ticket; remove unintended public or cross-account access and rotate exposed credentials.
Why it matters: AMI permissions can expose machine images, embedded secrets, and trusted software to unintended accounts.
Evidence: CloudTrail supplied the image identifier and launch-permission change shown above; image contents are not inspected by this alert.
Monitoring: AWS CloudTrail EC2 ModifyImageAttribute events.
Impact: The image's distribution boundary changed; exposure depends on the resulting permissions and image contents.
Recovery: No automatic recovery is claimed; manual resolution requires a verified approved permission set and credential review when exposure occurred.""",
            "compute.instance.modify": """EC2 instance configuration changed · i-0123
What happened: An EC2 instance attribute changed.
Facts: Instance: i-0123
Instance type: m7g.large
Source/destination check: False
Account: 111111111111
Region: us-east-1
Actor: arn:aws:iam::111111111111:user/operator
When: 2026-08-29T10:00:00Z
Decision: Confirm the changed instance attribute is approved and does not alter routing, workload capacity, or host security unexpectedly.
Next steps: Review the before/after attribute and owner; validate application health and network behavior; revert through the approved change process if unauthorized.
Why it matters: Instance attributes can change workload capacity or network behavior even when no security finding is raised.
Evidence: CloudTrail supplied the instance attribute values shown above; unavailable before/after values are intentionally omitted.
Monitoring: AWS CloudTrail EC2 ModifyInstanceAttribute events.
Impact: The instance configuration differs from its prior state; operational impact depends on the changed attribute.
Recovery: No automatic rollback is claimed; manual resolution is a verified approved configuration or a follow-up corrective change.""",
        }
        for action, extra in fixtures.items():
            profile = normalize_profile({"module": "aws.compute", "event_kind": action})
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action, **extra), profile["message_template"])
            self.assertEqual(body, expected[action])
            self.assertEqual(body, body.strip())
            for label in ("What happened:", "Facts:", "Decision:", "Next steps:", "Evidence:", "Recovery:"):
                self.assertIn(label, body)
            self.assertNotIn("not reported", body.lower())
            self.assertNotIn("None", body)
        for action in COMPUTE_EVENTS:
            profile = normalize_profile({"module": "aws.compute", "event_kind": action})
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action, target_id=None), profile["message_template"])
            self.assertNotIn(" ·", body.splitlines()[0])
        for action in COMPUTE_EVENTS:
            profile = normalize_profile({"module": "aws.compute", "event_kind": action})
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action), profile["message_template"])
            self.assertNotIn("None", body)
            self.assertNotIn("not reported", body.lower())

    def test_real_slack_payload_and_distinct_recovery_language(self):
        event = _event("compute.ami.modify", image_id="ami-0123", ami_public=True)
        profile = normalize_profile({"module": "aws.compute", "event_kind": event.action})
        body = channels._render(channels.Channel(name="security", type="slack", url=""), event, profile["message_template"])
        captured = {}
        original = channels._post_json
        try:
            channels._post_json = lambda url, payload, timeout=10: (captured.update({"url": url, "payload": payload}) or (True, "HTTP 200"))
            self.assertEqual(channels._send_slack({"url": "https://hooks.slack.test"}, body, event), (True, "HTTP 200"))
        finally:
            channels._post_json = original
        text = captured["payload"]["attachments"][0]["text"]
        self.assertIn("AMI", text)
        self.assertIn("ami-0123", text)
        self.assertIn("exposure", text.lower())
        imds = normalize_profile({"module": "aws.compute", "event_kind": "compute.imds.modify"})
        self.assertNotEqual(profile["content"]["recovery"], imds["content"]["recovery"])

    def test_guidance_preview_and_coverage(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.compute")
        self.assertEqual(module["content_status"], "rolled_out")
        self.assertEqual(module["content_rollout_stage"], "11-platform")
        by_key = {item["key"]: item for item in module["events"]}
        for action in COMPUTE_EVENTS:
            profile = normalize_profile({"module": "aws.compute", "event_kind": action})
            self.assertTrue(build_preview_event(profile).extra or build_preview_event(profile).target.id)
            self.assertGreater(len(by_key[action]["available_fields"]), 5)
            self.assertEqual(module_for_event_kind(action), "aws.compute")
        self.assertEqual(next(item for item in build_coverage([], []) if item["key"] == "aws.compute")["content_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()
