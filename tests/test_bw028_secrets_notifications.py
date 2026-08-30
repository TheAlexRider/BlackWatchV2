from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Severity, Source, Target
from blackwatch.modules.aws_cloudtrail import AwsCloudTrailAdapter, _ACTION_MAP
from blackwatch.modules.base import IngestContext
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, normalize_profile


SECRETS_EVENTS = {
    "secrets.secret.create",
    "secrets.secret.update",
    "secrets.secret.restore",
    "secrets.secret.delete",
}


def _profile(action):
    return normalize_profile({"module": "aws.secrets", "event_kind": action})


def _event(action, **extra):
    return Event(
        source=Source(module="aws.cloudtrail", vendor="aws", account="111111111111", region="us-east-1"),
        category=Category.iam,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(principal="arn:aws:iam::111111111111:user/operator", source_ip="198.51.100.20"),
        target=Target(id=extra.pop("secret_arn", "arn:aws:secretsmanager:us-east-1:111111111111:secret:prod/db"), type="aws.secretsmanager", name=extra.pop("secret_name", "prod/db")),
        extra=extra,
    )


def _cloudtrail(event_name, request=None, response=None):
    return {
        "eventName": event_name,
        "eventSource": "secretsmanager.amazonaws.com",
        "eventTime": "2026-08-29T10:00:00Z",
        "awsRegion": "us-east-1",
        "sourceIPAddress": "198.51.100.20",
        "recipientAccountId": "111111111111",
        "userIdentity": {"type": "IAMUser", "userName": "operator", "arn": "arn:aws:iam::111111111111:user/operator"},
        "requestParameters": request or {},
        "responseElements": response or {},
        "eventID": f"secrets-{event_name}",
    }


class Bw028SecretsNotificationTests(unittest.TestCase):
    def test_secret_values_are_redacted_from_raw_and_persistence_payload(self):
        raw = _cloudtrail(
            "UpdateSecret",
            {"secretId": "prod/db", "SecretString": "request-secret", "nested": {"secretBinary": "request-binary"}},
            {"ARN": "arn:aws:secretsmanager:us-east-1:111111111111:secret:prod/db", "SecretString": "response-secret", "Nested": {"SECRETBINARY": "response-binary"}},
        )
        event = AwsCloudTrailAdapter().parse(raw, IngestContext(module="aws.cloudtrail", transport="queue"))[0]

        self.assertEqual(event.extra["secret_name"], "prod/db")
        self.assertNotIn("request-secret", repr(event.raw))
        self.assertNotIn("request-binary", repr(event.raw))
        self.assertNotIn("response-secret", repr(event.raw))
        self.assertNotIn("response-binary", repr(event.raw))

        # storage.insert_event persists Event.raw directly as its JSONB raw
        # column; this models that exact persistence payload without needing a
        # live database driver.
        persisted_raw = event.raw
        self.assertNotIn("request-secret", repr(persisted_raw))
        self.assertNotIn("request-binary", repr(persisted_raw))
        self.assertNotIn("response-secret", repr(persisted_raw))
        self.assertNotIn("response-binary", repr(persisted_raw))
        self.assertEqual(persisted_raw["requestParameters"]["secretId"], "prod/db")
        self.assertEqual(persisted_raw["responseElements"]["ARN"], "arn:aws:secretsmanager:us-east-1:111111111111:secret:prod/db")

    def test_every_secrets_producer_action_is_cataloged_or_explicitly_non_notifying(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.secrets")
        catalog_events = {item["key"] for item in module["events"]}
        inventory = module.get("producer_event_inventory") or {}
        producer_actions = {
            action for action, category in _ACTION_MAP.values()
            if category is Category.iam and action.startswith("secrets.")
        }
        self.assertEqual(producer_actions, catalog_events | set(inventory))
        self.assertEqual(inventory.get("secrets.secret.get_value"), "future: non-notifying raw secret access")

    def test_four_lifecycle_events_have_distinct_rolled_out_contracts(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.secrets")
        events = {item["key"]: item for item in module["events"]}
        self.assertEqual(set(events), SECRETS_EVENTS)
        self.assertTrue(all(item["content_status"] == "rolled_out" for item in events.values()))
        self.assertEqual(module["content_gap_count"], 0)
        self.assertEqual(module_for_event_kind("secrets.secret.update"), "aws.secrets")
        self.assertEqual(len({item["defaults"]["title"] for item in events.values()}), 4)

    def test_cloudtrail_normalizes_secret_fields_without_secret_value(self):
        raw = _cloudtrail(
            "UpdateSecret",
            {"secretId": "prod/db", "description": "production database", "kmsKeyId": "key-123"},
            {"arn": "arn:aws:secretsmanager:us-east-1:111111111111:secret:prod/db", "name": "prod/db", "versionId": "v2", "versionStages": ["AWSCURRENT"]},
        )
        event = AwsCloudTrailAdapter().parse(raw, IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(event.action, "secrets.secret.update")
        self.assertEqual(event.target.id, "prod/db")
        self.assertEqual(event.extra["secret_name"], "prod/db")
        self.assertEqual(event.extra["secret_arn"], "arn:aws:secretsmanager:us-east-1:111111111111:secret:prod/db")
        self.assertEqual(event.extra["version_id"], "v2")
        self.assertEqual(event.extra["version_stages"], ["AWSCURRENT"])
        self.assertNotIn("SecretString", event.extra)
        self.assertNotIn("secret_value", event.extra)

    def test_complete_lifecycle_email_plain_text_goldens_are_actionable(self):
        fixtures = {
            "secrets.secret.create": {"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "description": "database credential", "kms_key_id": "key-123", "version_stages": ["AWSCURRENT"]},
            "secrets.secret.update": {"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "change_type": "value rotated", "version_id": "v2", "version_stages": ["AWSCURRENT"], "consuming_service": "payments-api"},
            "secrets.secret.restore": {"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "recovery_window_days": 7, "consuming_service": "payments-api"},
            "secrets.secret.delete": {"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "recovery_window_days": 7, "consuming_service": "payments-api"},
        }
        for action, extra in fixtures.items():
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action, **extra), _profile(action)["message_template"])
            self.assertEqual(body, body.strip())
            self.assertNotIn("None", body)
            self.assertNotIn("secretstring", body.lower())
            self.assertNotIn("secretstring", body.lower())
            self.assertNotIn("secretbinary", body.lower())
            for label in ("What happened:", "Facts:", "Decision:", "Next steps:", "Evidence:", "Recovery:"):
                self.assertIn(label, body)
            self.assertIn(extra["secret_name"], body)
            self.assertNotEqual(body, _event(action, **extra).action)

    def test_partial_lifecycle_rendering_omits_unavailable_fields_and_recovery_claims(self):
        for action in SECRETS_EVENTS:
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action), _profile(action)["message_template"])
            self.assertNotIn("None", body)
            self.assertNotIn("not reported", body.lower())
            self.assertNotIn("secretstring", body.lower())
            self.assertNotIn("automatically restored", body.lower())
            if action == "secrets.secret.delete":
                self.assertIn("manual", body.lower())

    def test_chat_golden_is_real_slack_payload_and_never_contains_secret_value(self):
        event = _event("secrets.secret.update", secret_name="prod/db", change_type="value rotated", version_id="v2", secret_value="DO-NOT-SEND").model_copy(update={"severity": Severity.high})
        body = channels._render(channels.Channel(name="security", type="slack", url=""), event, _profile(event.action)["message_template"])
        captured = {}

        def capture(url, payload, timeout=10):
            captured.update({"url": url, "payload": payload, "timeout": timeout})
            return True, "HTTP 200"

        original = channels._post_json
        try:
            channels._post_json = capture
            result = channels._send_slack({"url": "https://hooks.slack.test"}, body, event)
        finally:
            channels._post_json = original
        self.assertEqual(result, (True, "HTTP 200"))
        attachment = captured["payload"]["attachments"][0]
        self.assertEqual(captured["url"], "https://hooks.slack.test")
        self.assertEqual(attachment["footer"], "BlackWatch · high")
        self.assertIn("Secret updated", attachment["text"])
        self.assertNotIn("DO-NOT-SEND", attachment["text"])

    def test_guidance_preview_and_coverage_expose_secret_fields(self):
        profile = _profile("secrets.secret.update")
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.secrets")
        event = next(item for item in module["events"] if item["key"] == "secrets.secret.update")
        for field in ("{secret_name}", "{secret_arn}", "{version_id}", "{version_stages}", "{change_type}"):
            self.assertIn(field, event["available_fields"])
        self.assertNotIn("{secret_value}", event["available_fields"])
        self.assertTrue(build_preview_event(profile).extra)
        coverage = next(item for item in build_coverage([], []) if item["key"] == "aws.secrets")
        self.assertEqual(coverage["content_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()
