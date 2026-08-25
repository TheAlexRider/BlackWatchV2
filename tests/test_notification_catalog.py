import unittest

from blackwatch.notify.catalog import (
    MODULE_CARDS,
    MODULE_CATALOG,
    build_coverage,
    canonical_module_keys,
)


class NotificationCatalogTests(unittest.TestCase):
    def test_module_cards_and_route_catalog_share_the_canonical_modules(self):
        expected = canonical_module_keys()
        self.assertEqual([item["key"] for item in MODULE_CARDS], expected)
        self.assertEqual([item["key"] for item in MODULE_CATALOG], expected)

    def test_coverage_reports_configured_fallback_muted_and_unconfigured(self):
        saved_profiles = [
            {
                "id": "profile:aws.rds:rds.auth.failure",
                "module": "aws.rds",
                "event_kind": "rds.auth.failure",
                "enabled": True,
                "channels": ["security-slack"],
                "severities": ["high", "critical"],
            },
            {
                "id": "profile:ecs.probe:service.down",
                "module": "ecs.probe",
                "event_kind": "service.down",
                "enabled": False,
                "channels": ["security-slack"],
                "severities": ["high", "critical"],
            },
        ]
        legacy_rules = [
            {
                "id": "legacy-rds-route",
                "name": "route:aws.rds:high",
                "enabled": True,
                "channels": ["ops-slack"],
                "match": {
                    "all": [
                        {"field": "source.module", "op": "equals", "value": "aws.rds"},
                        {"field": "severity", "op": "in", "value": ["high", "critical"]},
                    ]
                },
            }
        ]

        coverage = build_coverage(saved_profiles, legacy_rules)
        events = {
            item["event_kind"]: item
            for module in coverage
            if module["key"] == "aws.rds"
            for item in module["events"]
        }
        probe_events = {
            item["event_kind"]: item
            for module in coverage
            if module["key"] == "ecs.probe"
            for item in module["events"]
        }

        self.assertEqual(events["rds.auth.failure"]["state"], "configured")
        self.assertEqual(events["rds.auth.burst"]["state"], "fallback")
        self.assertEqual(events["rds.auth.burst"]["covered_severities"], ["high", "critical"])
        self.assertEqual(probe_events["service.down"]["state"], "muted")
        self.assertEqual(probe_events["service.down"]["high_critical_gap"], False)
        self.assertEqual(events["rds.query.function"]["state"], "fallback")
        self.assertTrue(events["rds.auth.failure"]["profile_id"].startswith("profile:aws.rds:"))

    def test_unconfigured_high_signal_event_is_flagged_as_a_gap(self):
        coverage = build_coverage([], [])
        gaps = [
            event
            for module in coverage
            for event in module["events"]
            if event["high_critical_gap"]
        ]
        self.assertTrue(gaps)
        self.assertTrue(all(event["state"] == "unconfigured" for event in gaps))

    def test_coverage_exposes_content_rollout_separately_from_delivery_state(self):
        coverage = build_coverage([], [])
        vpn = next(item for item in coverage if item["key"] == "vpn.openvpn")
        failure = next(item for item in vpn["events"] if item["event_kind"] == "vpn.auth.failure")

        self.assertEqual(failure["state"], "unconfigured")
        self.assertEqual(failure["content_status"], "rolled_out")
        self.assertEqual(failure["rollout_stage"], "1-vpn")
        self.assertFalse(failure["content_gap"])
        self.assertEqual(vpn["content_status"], "rolled_out")
        self.assertEqual(vpn["content_rollout_stage"], "1-vpn")

    def test_every_catalog_module_has_rollout_metadata_and_backlog_visibility(self):
        coverage = build_coverage([], [])

        self.assertTrue(coverage)
        self.assertTrue(all(item["content_status"] in {"generic", "rolled_out"} for item in coverage))
        self.assertTrue(all(item["content_rollout_stage"] for item in coverage))
        self.assertTrue(all("content_gap_count" in item for item in coverage))
        self.assertTrue(any(item["content_status"] == "generic" for item in coverage))


if __name__ == "__main__":
    unittest.main()
