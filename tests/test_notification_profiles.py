from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from blackwatch.notify import profile_service
from blackwatch.notify.profiles import (
    NOTIFICATION_CATALOG,
    build_profile_match,
    compile_message_template,
    normalize_profile,
)


class NotificationProfileTests(unittest.TestCase):
    def test_profile_listing_skips_non_notifying_catalog_events(self):
        with patch.object(profile_service.storage, "list_notification_profiles", return_value=[]):
            profiles = profile_service.list_profiles()

        event_keys = {profile["event_kind"] for profile in profiles}
        self.assertNotIn("posture.finding.open", event_keys)
        self.assertIn("aws.posture.finding.new", event_keys)

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
                "aws.compute",
                "aws.storage",
                "findings",
            }.issubset(modules)
        )

    def test_catalog_has_one_editable_profile_for_each_alert_kind(self):
        events = [event["key"] for module in NOTIFICATION_CATALOG for event in module["events"]]
        self.assertEqual(len(events), len(set(events)))
        self.assertTrue(
            {
                "host.cpu.anomaly",
                "rds.parameter_group.modify",
                "s3.bucket.bpa.delete",
                "backup.copy_job.start",
                "compute.imds.modify",
                "storage.snapshot.modify",
                "vpn.cert.expiring.warning",
                "aws.posture.finding.resolved",
                "finding.malware.detected",
            }.issubset(events)
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

    def test_service_and_probe_alert_kinds_have_separate_contextual_profiles(self):
        module = next(entry for entry in NOTIFICATION_CATALOG if entry["key"] == "ecs.probe")
        events = {event["key"]: event for event in module["events"]}
        self.assertTrue(
            {
                "service.down",
                "service.degraded",
                "service.unknown",
                "service.up",
                "probe.agent.stale",
                "probe.agent.recovered",
                "probe.agent.first_seen",
            }.issubset(events)
        )
        self.assertIn("{service_name}", events["service.down"]["available_fields"])
        self.assertIn("{downtime}", events["service.up"]["available_fields"])
        self.assertIn("{last_report}", events["probe.agent.stale"]["available_fields"])

    def test_context_tokens_compile_to_event_extra_fields(self):
        template = compile_message_template(
            {
                "title": "{service_name} in {vpc}",
                "what_happened": "Signal: {error_signal}; latency {latency_ms} ms.",
                "evidence": "{consecutive_failures} consecutive failures.",
                "monitoring_method": "{monitoring_method} / tier {monitor_tier}.",
                "impact": "{monitoring_impact}; downtime {downtime}.",
                "recovery": "Last report: {last_report}; recovery after {consecutive_successes} successes.",
            }
        )
        self.assertIn("event.extra.service_name", template)
        self.assertIn("event.extra.error_signal", template)
        self.assertIn("event.extra.consecutive_failures", template)
        self.assertIn("event.extra.monitoring_impact", template)
        self.assertIn("event.extra.downtime_seconds", template)

    def test_every_catalog_event_exposes_safe_template_fields(self):
        for module in NOTIFICATION_CATALOG:
            for event in module["events"]:
                self.assertTrue(event["available_fields"], f"{module['key']}/{event['key']}")
                self.assertIn("{evidence}", event["available_fields"])
                self.assertIn("{monitoring_method}", event["available_fields"])

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
