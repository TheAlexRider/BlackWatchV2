from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, ActorType, Category, Event, Source, Target
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import (
    NOTIFICATION_CATALOG,
    build_preview_event,
    build_profile_match,
    normalize_profile,
)


def _profile(event_kind: str = "ueba.anomaly") -> dict:
    return normalize_profile({"module": "ueba", "event_kind": event_kind})


def _event(action: str = "iam.anomaly.first_seen_source_ip", **extra) -> Event:
    return Event(
        source=Source(module="aws.iam", account="prod", region="us-east-1"),
        category=Category.iam,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(principal="alice", type=ActorType.user, source_ip="203.0.113.7", user_agent="aws-cli/2.1"),
        target=Target(id="account-1", name="production account"),
        extra=extra,
    )


class Bw023UebaNotificationTests(unittest.TestCase):
    def test_runtime_action_resolves_to_dynamic_ueba_contract(self):
        profile = _profile("iam.anomaly.first_seen_source_ip")
        self.assertEqual(profile["module"], "ueba")
        self.assertEqual(profile["event_kind"], "iam.anomaly.first_seen_source_ip")
        self.assertEqual(profile["content_status"], "rolled_out")
        self.assertIn("baseline", profile["message_template"].lower())

    def test_catalog_has_pattern_not_fake_static_ueba_event(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "ueba")
        keys = {event["key"] for event in module["events"]}
        self.assertNotIn("ueba.anomaly", keys)
        self.assertIn("<category>.anomaly.first_seen_*", keys)
        self.assertEqual(module_for_event_kind("iam.anomaly.first_seen_source_ip"), "ueba")
        self.assertEqual(module["content_gap_count"], 0)

    def test_match_covers_only_first_seen_anomaly_family(self):
        match = build_profile_match("ueba", "ueba.anomaly", ["medium", "high"])
        self.assertEqual(match["all"][0], {"field": "action", "op": "icontains", "value": ".anomaly.first_seen_"})
        from blackwatch.rules.operators import OPERATORS
        self.assertTrue(OPERATORS[match["all"][0]["op"]]("iam.anomaly.first_seen_source_ip", match["all"][0]["value"]))
        self.assertFalse(OPERATORS[match["all"][0]["op"]]("iam.anomaly.burst", match["all"][0]["value"]))

    def test_complete_email_and_chat_rendering_is_actionable(self):
        event = _event(
            dimension="source_ip",
            baseline_value="203.0.113.7",
            trigger_action="iam.role.assume",
            principal_id="alice",
            principal_type="user",
        )
        template = _profile("iam.anomaly.first_seen_source_ip")["message_template"]
        email = channels._render(channels.Channel(name="security", type="email", url=""), event, template)
        chat = channels._render(channels.Channel(name="security", type="slack", url=""), event, template)
        for rendered in (email, chat):
            self.assertIn("New Source IP observed", rendered)
            self.assertIn("Dimension: source_ip", rendered)
            self.assertIn("Value: 203.0.113.7", rendered)
            self.assertIn("proof of compromise", rendered)
            self.assertIn("Review the principal's recent access", rendered)
            self.assertNotIn("unknown principal", rendered.lower())

    def test_partial_rendering_omits_unavailable_ueba_facts(self):
        partial = _event(dimension="source_ip").model_copy(update={"actor": Actor()})
        rendered = channels._render(
            channels.Channel(name="security", type="email", url=""),
            partial,
            _profile("iam.anomaly.first_seen_source_ip")["message_template"],
        )
        self.assertNotIn("Value:", rendered)
        self.assertNotIn("Principal:", rendered)
        self.assertNotIn("Source country:", rendered)
        self.assertNotIn("Source ASN:", rendered)
        self.assertNotIn("None", rendered)

    def test_preview_and_coverage_expose_runtime_contract(self):
        profile = _profile("iam.anomaly.first_seen_source_ip")
        preview = build_preview_event(profile)
        self.assertEqual(preview.action, "iam.anomaly.first_seen_source_ip")
        self.assertIn("baseline_value", preview.extra)
        coverage = build_coverage([], [])
        module = next(item for item in coverage if item["key"] == "ueba")
        event = next(item for item in module["events"] if item["event_kind"] == "<category>.anomaly.first_seen_*")
        self.assertEqual(event["content_status"], "rolled_out")
        self.assertFalse(event["content_gap"])


if __name__ == "__main__":
    unittest.main()
