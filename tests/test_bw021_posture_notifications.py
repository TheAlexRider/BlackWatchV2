from datetime import datetime, timezone
import unittest
import importlib
import sys
import types
from unittest.mock import patch

from blackwatch.event import Event, Source, Target
from blackwatch.notify import channels
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, normalize_profile


POSTURE_EVENTS = {
    "network.sg.instance_attach",
    "posture.finding.open",
    "aws.posture.finding.new",
    "aws.posture.finding.resolved",
}


def _profile(event_kind: str) -> dict:
    return normalize_profile({"module": "aws.posture", "event_kind": event_kind})


def _event(action: str, **extra) -> Event:
    return Event(
        source=Source(module="aws.posture", vendor="aws", account="111122223333", region="us-west-1"),
        action=action,
        event_time=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        severity="informational" if action.endswith("resolved") else "high",
        target=Target(id=extra.pop("target_id", "sg-0abc"), type="aws.sg", name=extra.pop("target_name", None)),
        extra=extra,
    )


class Bw021PostureNotificationTests(unittest.TestCase):
    def test_catalog_inventories_producer_ownership_and_future_open_key(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.posture")
        events = {item["key"]: item for item in module["events"]}

        self.assertEqual(set(events), POSTURE_EVENTS)
        self.assertEqual(events["network.sg.instance_attach"]["producer_status"], "producer")
        self.assertEqual(events["aws.posture.finding.new"]["producer_status"], "projection")
        self.assertEqual(events["aws.posture.finding.resolved"]["producer_status"], "projection")
        self.assertEqual(events["posture.finding.open"]["producer_status"], "future")
        self.assertEqual(events["posture.finding.open"]["notification_status"], "non_notifying")
        with self.assertRaises(ValueError):
            _profile("posture.finding.open")
        self.assertIn("aws.posture.finding", events["aws.posture.finding.new"]["producer_keys"])
        self.assertIn("aws.posture.scan.completed", events["aws.posture.finding.resolved"]["producer_keys"])

    def test_each_notifying_event_has_a_unique_actionable_contract(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.posture")
        events = [item for item in module["events"] if item["notification_status"] == "notifying"]

        self.assertEqual(len(events), 3)
        for field in ("title", "what_happened", "facts", "decision", "next_steps", "evidence", "recovery"):
            self.assertEqual(len({item["defaults"][field] for item in events}), len(events), field)
            self.assertTrue(all(item["defaults"][field] for item in events), field)

    def test_instance_attachment_and_finding_lifecycle_are_distinct(self):
        attach = _event("network.sg.instance_attach", target_id="i-0123", instance_id="i-0123", sg_ids=["sg-0abc"])
        finding = _event(
            "aws.posture.finding.new",
            finding_id="finding-1",
            resource_id="sg-0abc",
            resource_type="sg",
            finding_type="public_ingress_risky_port",
            severity="critical",
            evidence={"ports": [22], "cidrs": ["0.0.0.0/0"]},
        )
        self.assertIn("instance", channels._render(channels.Channel(name="email", type="email", url=""), attach, _profile(attach.action)["message_template"]).lower())
        self.assertIn("finding-1", channels._render(channels.Channel(name="email", type="email", url=""), finding, _profile(finding.action)["message_template"]))
        self.assertNotEqual(_profile(attach.action)["message_template"], _profile(finding.action)["message_template"])

    def test_complete_posture_fixture_has_email_and_chat_resolution_semantics(self):
        event = _event(
            "aws.posture.finding.resolved",
            finding_id="finding-1",
            resource_id="sg-0abc",
            resource_type="sg",
            finding_type="public_ingress_risky_port",
            severity="high",
            evidence={"ports": [22], "cidrs": ["0.0.0.0/0"]},
            resolved_at="2026-08-25T10:00:00Z",
        )
        profile = _profile(event.action)
        email = channels._render(channels.Channel(name="email", type="email", url=""), event, profile["message_template"])
        chat = channels._render(channels.Channel(name="security", type="slack", url=""), event, profile["message_template"])

        self.assertEqual(email, chat)
        self.assertIn("AWS posture finding resolved", email)
        self.assertIn("finding-1", email)
        self.assertIn("manual", email.lower())
        self.assertIn("security-group attachment", email.lower())

    def test_plain_text_notification_matches_golden_body(self):
        event = _event(
            "aws.posture.finding.new",
            finding_id="finding-1", resource_id="sg-0abc", resource_type="sg",
            finding_type="public_ingress_risky_port", severity="critical",
            account="111122223333", region="us-west-1", evidence={"ports": [22]},
        )
        rendered = channels._render(channels.Channel(name="email", type="email", url=""), event, _profile(event.action)["message_template"])
        self.assertEqual(rendered, """New AWS posture finding · finding-1
What happened: The posture projection recorded a finding that is active for the first time or after a prior resolution.
Facts: Finding ID: finding-1
Resource: sg-0abc (sg)Control/finding: public_ingress_risky_port
Severity: critical
Account: 111122223333
Region: us-west-1
When: 2026-08-25T10:00:00Z
Decision: Determine whether the finding is an unauthorized posture condition, an approved exception, or a false positive.
Next steps: Verify the resource and control evidence, identify the owner, preserve the finding ID, and remediate or document the approved exception.
Why it matters: A posture finding indicates a preventive control or exposure condition that remains traceable until resolved.
Evidence: The producer supplied this evidence: {'ports': [22]}Monitoring: AWS posture scan findings and the posture lifecycle projection.
Impact: The recorded control condition may leave the resource exposed or outside the intended posture; broader impact is not inferred.
Recovery: Pair a later aws.posture.finding.resolved event by finding ID; manual resolution is remediation or an owner-approved exception.""")

    def test_projection_pairs_resolution_by_finding_id_and_supports_reopen(self):
        fake_storage = types.SimpleNamespace(
            upsert_posture_finding=None,
            list_unresolved_finding_ids_for_account=None,
            get_posture_finding=None,
            mark_posture_finding_resolved=None,
        )
        previous_storage = sys.modules.get("blackwatch.storage")
        sys.modules["blackwatch.storage"] = fake_storage
        try:
            projection = importlib.import_module("blackwatch.posture.projection")
        finally:
            if previous_storage is None:
                sys.modules.pop("blackwatch.storage", None)
            else:
                sys.modules["blackwatch.storage"] = previous_storage
        source = _event("aws.posture.finding", finding_id="finding-1", account="111122223333")
        with patch.object(projection.storage, "upsert_posture_finding", side_effect=[True, True]), \
             patch.object(projection.storage, "list_unresolved_finding_ids_for_account", return_value={"finding-1", "finding-2"}), \
             patch.object(projection.storage, "get_posture_finding", return_value={
                 "resource_id": "sg-0abc", "resource_type": "sg", "finding_type": "risky",
                 "severity": "high", "region": "us-west-1", "account": "111122223333", "evidence": {},
             }), \
             patch.object(projection.storage, "mark_posture_finding_resolved") as mark:
            first = projection.project(source)
            resolved = projection.project(_event("aws.posture.scan.completed", account="111122223333", finding_ids=["finding-1"]))
            reopened = projection.project(source)

        self.assertEqual([event.action for event in first], ["aws.posture.finding.new"])
        self.assertEqual([event.extra["finding_id"] for event in resolved], ["finding-2"])
        self.assertEqual([event.action for event in reopened], ["aws.posture.finding.new"])
        mark.assert_called_once_with("finding-2", resolved[0].event_time)

    def test_partial_posture_fixture_omits_unavailable_values_and_preview_is_named(self):
        for action in ("network.sg.instance_attach", "aws.posture.finding.new", "aws.posture.finding.resolved"):
            event = _event(action)
            rendered = channels._render(channels.Channel(name="email", type="email", url=""), event, _profile(action)["message_template"])
            self.assertNotIn("unknown", rendered.lower())
            self.assertNotIn("not reported", rendered.lower())
            self.assertNotIn("threshold", rendered.lower())
            if action.startswith("aws.posture.finding"):
                self.assertNotIn("Evidence:", rendered)
            preview = build_preview_event(_profile(action))
            self.assertEqual(preview.action, action)


if __name__ == "__main__":
    unittest.main()
