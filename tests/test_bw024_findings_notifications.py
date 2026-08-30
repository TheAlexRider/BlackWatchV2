from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Source, Target
from blackwatch.modules.base import IngestContext
from blackwatch.modules.generic import GenericAdapter
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, build_profile_match, normalize_profile


def _profile(event_kind: str) -> dict:
    return normalize_profile({"module": "findings", "event_kind": event_kind})


def _event(action: str = "finding.malware.detected", **extra) -> Event:
    return Event(
        source=Source(module="custom.detector", vendor="clamav", account="prod", region="us-east-1"),
        category=Category.finding,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(principal="scanner", source_ip="203.0.113.10"),
        target=Target(id="s3://uploads/invoice.xlsx", type="s3.object", name="invoice.xlsx"),
        extra=extra,
    )


class Bw024FindingNotificationTests(unittest.TestCase):
    def test_catalog_covers_typed_and_custom_finding_families(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "findings")
        keys = {event["key"] for event in module["events"]}
        self.assertIn("finding.malware.detected", keys)
        self.assertIn("<finding>.detected", keys)
        self.assertEqual(module_for_event_kind("finding.phishing.detected"), "findings")
        self.assertEqual(module_for_event_kind("finding.malware.detected"), "findings")
        self.assertEqual(module["content_gap_count"], 0)

    def test_custom_finding_profile_matches_only_detected_actions(self):
        profile = _profile("finding.phishing.detected")
        self.assertEqual(profile["content_status"], "rolled_out")
        match = build_profile_match("findings", "<finding>.detected", ["high"])
        from blackwatch.rules.operators import OPERATORS
        clause = match["all"][0]
        self.assertTrue(OPERATORS[clause["op"]]("finding.phishing.detected", clause["value"]))
        self.assertFalse(OPERATORS[clause["op"]]("finding.phishing.resolved", clause["value"]))
        generic = build_profile_match("findings", "finding.detected", ["high"])["all"][0]
        self.assertTrue(OPERATORS[generic["op"]]("finding.detected", generic["value"]))

    def test_complete_malware_email_and_chat_rendering_is_actionable(self):
        event = _event(
            signature="Win.Trojan.Foo",
            detection="Eicar-Test-Signature",
            resource="s3://uploads/invoice.xlsx",
            object_path="uploads/invoice.xlsx",
            file_hash="sha256:abc123",
            scan_time="2026-08-29T09:59:00Z",
            engine="ClamAV 1.4",
            confidence="high",
            containment_state="not_contained",
            owner="finance-platform",
            evidence={"rule": "malware-signature", "bytes": 1234},
            custom_signal="retain-this-field",
        )
        template = _profile("finding.malware.detected")["message_template"]
        rendered = [channels._render(channels.Channel(name="security", type=kind, url=""), event, template) for kind in ("email", "slack")]
        for body in rendered:
            self.assertIn("Malware detected", body)
            self.assertIn("Win.Trojan.Foo", body)
            self.assertIn("sha256:abc123", body)
            self.assertIn("'rule': 'malware-signature'", body)
            self.assertIn("Contain", body)
            self.assertIn("manual", body.lower())
            self.assertNotIn("unknown", body.lower())

    def test_partial_finding_omits_unavailable_typed_facts(self):
        body = channels._render(
            channels.Channel(name="security", type="email", url=""),
            _event(signature="Only.Signature"),
            _profile("finding.malware.detected")["message_template"],
        )
        self.assertIn("Only.Signature", body)
        self.assertNotIn("Hash:", body)
        self.assertNotIn("Owner:", body)
        self.assertNotIn("Evidence:", body)
        self.assertNotIn("None", body)

    def test_generic_webhook_preserves_arbitrary_extra_evidence(self):
        event = GenericAdapter().parse(
            {"category": "finding", "action": "finding.phishing.detected", "extra": {"vendor_case": "CASE-42", "nested": {"score": 9}}},
            IngestContext(module="custom.detector", transport="webhook"),
        )[0]
        self.assertEqual(event.extra["vendor_case"], "CASE-42")
        self.assertEqual(event.extra["nested"]["score"], 9)

    def test_preview_and_coverage_are_rolled_out(self):
        profile = _profile("finding.malware.detected")
        self.assertIn("signature", build_preview_event(profile).extra)
        module = next(item for item in build_coverage([], []) if item["key"] == "findings")
        self.assertEqual(module["content_gap_count"], 0)
        self.assertTrue(all(event["content_status"] == "rolled_out" for event in module["events"]))


if __name__ == "__main__":
    unittest.main()
