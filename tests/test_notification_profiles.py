from datetime import datetime, timezone
import unittest

from blackwatch.notify.profiles import (
    NOTIFICATION_CATALOG,
    build_profile_match,
    compile_message_template,
    normalize_profile,
)


class NotificationProfileTests(unittest.TestCase):
    def test_catalog_covers_the_product_modules(self):
        modules = {entry["key"] for entry in NOTIFICATION_CATALOG}
        self.assertTrue(
            {
                "ec2.host",
                "aws.rds",
                "aws.iam",
                "aws.s3",
                "aws.api_gateway",
                "aws.posture",
                "aws.backup",
                "aws.efs",
                "aws.network",
                "aws.secrets",
                "vpn.openvpn",
                "ecs.probe",
                "cert",
                "ueba",
            }.issubset(modules)
        )

    def test_profile_match_is_scoped_to_one_alert_kind(self):
        match = build_profile_match("aws.rds", "rds.auth.failure", ["high", "critical"])
        self.assertEqual(
            match,
            {
                "all": [
                    {"field": "action", "op": "equals", "value": "rds.auth.failure"},
                    {"field": "severity", "op": "in", "value": ["high", "critical"]},
                ]
            },
        )

    def test_fim_alert_kinds_are_explicitly_cataloged(self):
        host = next(entry for entry in NOTIFICATION_CATALOG if entry["key"] == "ec2.host")
        kinds = {event["key"] for event in host["events"]}
        self.assertTrue(
            {
                "host.fim.created",
                "host.fim.modified",
                "host.fim.deleted",
                "host.fim.perm_changed",
                "host.fim.owner_changed",
            }.issubset(kinds)
        )

    def test_structured_message_compiles_to_plain_guided_sections(self):
        template = compile_message_template(
            {
                "title": "{{target_name}} needs attention",
                "what_happened": "BlackWatch detected {alert_type}.",
                "why_it_matters": "This may interrupt customer traffic.",
                "evidence": "Observed signal: {evidence}.",
                "monitoring_method": "Checked by {monitoring_method}.",
                "impact": "Impact: {impact}.",
                "next_steps": "Check the service owner and recent deploys.",
                "recovery": "Recovery is reported by {recovery_event}.",
                "runbook_url": "https://runbooks.example.invalid/service",
            }
        )
        self.assertIn("{{ event.target.name or event.target.id or 'unknown target' }} needs attention", template)
        self.assertIn("What happened: BlackWatch detected {{ event.action }}.", template)
        self.assertIn("Why it matters: This may interrupt customer traffic.", template)
        self.assertIn("Monitoring: Checked by {{ event.extra.monitoring_method or 'configured monitor' }}.", template)
        self.assertIn("Next steps: Check the service owner and recent deploys.", template)
        self.assertIn("Runbook: https://runbooks.example.invalid/service", template)

    def test_advanced_template_wins_without_dropping_profile_metadata(self):
        profile = normalize_profile(
            {
                "module": "aws.rds",
                "event_kind": "rds.auth.failure",
                "label": "Database login failure",
                "enabled": True,
                "severities": ["high"],
                "channels": ["ops-slack"],
                "advanced_template": "CUSTOM {{ event.action }}",
                "updated_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
            }
        )
        self.assertEqual(profile["module"], "aws.rds")
        self.assertEqual(profile["event_kind"], "rds.auth.failure")
        self.assertEqual(profile["message_template"], "CUSTOM {{ event.action }}")
        self.assertEqual(profile["severities"], ["high"])


if __name__ == "__main__":
    unittest.main()
