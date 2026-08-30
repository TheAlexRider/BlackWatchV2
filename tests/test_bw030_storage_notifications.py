from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Severity, Source, Target
from blackwatch.modules.aws_cloudtrail import AwsCloudTrailAdapter, _ACTION_MAP
from blackwatch.modules.base import IngestContext
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, normalize_profile


def _raw(request):
    return {"eventName": "ModifySnapshotAttribute", "eventSource": "ec2.amazonaws.com", "eventTime": "2026-08-29T10:00:00Z", "awsRegion": "us-east-1", "sourceIPAddress": "198.51.100.20", "recipientAccountId": "111111111111", "userIdentity": {"type": "IAMUser", "userName": "operator", "arn": "arn:aws:iam::111111111111:user/operator"}, "requestParameters": request, "responseElements": {}, "eventID": "storage-1"}


def _event(**extra):
    return Event(source=Source(module="aws.cloudtrail", vendor="aws", account="111111111111", region="us-east-1"), category=Category.storage, action="storage.snapshot.modify", event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc), severity=Severity.high, actor=Actor(principal="arn:aws:iam::111111111111:user/operator", source_ip="198.51.100.20"), target=Target(id=extra.pop("snapshot_id", "snap-0123"), type="aws.ebs_snapshot"), extra=extra)


class Bw030StorageNotificationTests(unittest.TestCase):
    def test_inventory_covers_every_ebs_storage_producer_action(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.storage")
        catalog = {event["key"] for event in module["events"]}
        inventory = module.get("producer_event_inventory") or {}
        producers = {action for action, category in _ACTION_MAP.values() if category is Category.storage and action.startswith("storage.")}
        self.assertEqual(producers, catalog | set(inventory))
        self.assertEqual(catalog, {"storage.snapshot.modify"})
        self.assertEqual(module["content_gap_count"], 0)

    def test_cloudtrail_normalizes_public_and_cross_account_scope(self):
        event = AwsCloudTrailAdapter().parse(_raw({"snapshotId": "snap-0123", "createVolumePermission": {"add": {"items": [{"userId": "222222222222"}, {"group": "all"}]}}}), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(event.action, "storage.snapshot.modify")
        self.assertEqual(event.extra["snapshot_id"], "snap-0123")
        self.assertTrue(event.extra["snapshot_public"])
        self.assertEqual(event.extra["snapshot_shared_accounts"], ["222222222222"])
        self.assertEqual(event.extra["snapshot_share_scope"], "public and cross-account")

    def test_cloudtrail_normalizes_removed_accounts_and_current_sharing_state(self):
        event = AwsCloudTrailAdapter().parse(_raw({
            "snapshotId": "snap-0123",
            "createVolumePermission": {
                "remove": {"items": [{"userId": "222222222222"}, {"group": "all"}]},
                "current": {"items": [{"userId": "333333333333"}]},
                "before": {"items": [{"userId": "222222222222"}, {"userId": "333333333333"}, {"group": "all"}]},
            },
        }), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(event.extra["snapshot_removed_accounts"], ["222222222222"])
        self.assertTrue(event.extra["snapshot_removed_public"])
        self.assertEqual(event.extra["snapshot_shared_accounts_before"], ["222222222222", "333333333333"])
        self.assertTrue(event.extra["snapshot_public_before"])
        self.assertEqual(event.extra["snapshot_shared_accounts_current"], ["333333333333"])
        self.assertFalse(event.extra["snapshot_public_current"])

        profile = normalize_profile({"module": "aws.storage", "event_kind": event.action})
        body = channels._render(channels.Channel(name="security", type="email", url=""), event, profile["message_template"])
        self.assertIn("Removed accounts: 222222222222", body)
        self.assertIn("Sharing before: public and cross-account", body)
        self.assertIn("Sharing now: cross-account", body)

    def test_exact_email_plain_text_golden(self):
        event = _event(snapshot_id="snap-0123", volume_id="vol-0456", snapshot_public=True, snapshot_shared_accounts=["222222222222"], snapshot_share_scope="public and cross-account", encrypted=True)
        profile = normalize_profile({"module": "aws.storage", "event_kind": event.action})
        body = channels._render(channels.Channel(name="security", type="email", url=""), event, profile["message_template"])
        expected = """EBS snapshot sharing changed · snap-0123
What happened: An EBS snapshot sharing permission changed.
Facts: Snapshot: snap-0123
Volume: vol-0456
Sharing scope: public and cross-account
Shared accounts: 222222222222
Public access: yes
Encrypted: True
Actor: arn:aws:iam::111111111111:user/operator
Account: 111111111111
Region: us-east-1
When: 2026-08-29T10:00:00Z
Decision: Treat public exposure as urgent; confirm the permission change is approved before relying on this snapshot for recovery.
Next steps: Remove public access immediately if unauthorized; review every shared account, snapshot contents, encryption, retention, and restore permissions; preserve the CloudTrail evidence and approved baseline.
Why it matters: EBS snapshots can contain recoverable copies of sensitive workloads and are directly restorable by permitted principals.
Evidence: CloudTrail supplied the snapshot permission change and the sharing scope shown above; data access is not inferred from this event alone.
Monitoring: AWS CloudTrail EC2 ModifySnapshotAttribute events.
Impact: The snapshot's restore boundary changed; public or cross-account access may expose stored data.
Recovery: No automatic recovery is claimed; manually resolve only after unintended sharing is removed and an approved, restorable snapshot configuration is verified."""
        self.assertEqual(body, expected)

    def test_partial_rendering_is_safe(self):
        body = channels._render(channels.Channel(name="security", type="email", url=""), _event(snapshot_id=None), normalize_profile({"module": "aws.storage", "event_kind": "storage.snapshot.modify"})["message_template"])
        self.assertNotIn("None", body)
        self.assertNotIn("not reported", body.lower())
        self.assertIn("manual", body.lower())

    def test_real_slack_payload_and_studio_metadata(self):
        event = _event(snapshot_id="snap-0123", snapshot_public=False, snapshot_shared_accounts=["222222222222"], snapshot_share_scope="cross-account")
        profile = normalize_profile({"module": "aws.storage", "event_kind": event.action})
        body = channels._render(channels.Channel(name="security", type="slack", url=""), event, profile["message_template"])
        captured = {}
        original = channels._post_json
        try:
            channels._post_json = lambda url, payload, timeout=10: (captured.update({"payload": payload}) or (True, "HTTP 200"))
            self.assertEqual(channels._send_slack({"url": "https://hooks.slack.test"}, body, event), (True, "HTTP 200"))
        finally:
            channels._post_json = original
        text = captured["payload"]["attachments"][0]["text"]
        self.assertIn("EBS snapshot sharing changed", text)
        self.assertIn("snap-0123", text)
        self.assertIn("cross-account", text.lower())
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.storage")
        self.assertEqual(module_for_event_kind(event.action), "aws.storage")
        self.assertEqual(next(item for item in build_coverage([], []) if item["key"] == "aws.storage")["content_gap_count"], 0)
        self.assertTrue(build_preview_event(profile).extra)


if __name__ == "__main__":
    unittest.main()
