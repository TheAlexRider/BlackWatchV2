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


if __name__ == "__main__":
    unittest.main()
