import unittest

from blackwatch.notify.profiles import (
    NOTIFICATION_CATALOG,
    build_preview_event,
    compile_message_template,
    normalize_profile,
)


class NotificationRenderingTests(unittest.TestCase):
    def test_action_first_template_puts_facts_and_next_steps_before_optional_context(self):
        rendered = compile_message_template(
            {
                "title": "VPN login failed",
                "what_happened": "A VPN login failed.",
                "facts": "User: atharva.kale\nSource IP: 107.197.154.253",
                "decision": "Decide whether the login was expected.",
                "next_steps": "1. Confirm the login was expected.\n2. Investigate if it was not.",
                "why_it_matters": "This may indicate credential abuse.",
                "evidence": "AUTH_FAILED",
                "monitoring_method": "OpenVPN authentication log",
                "impact": "",
                "recovery": "",
                "runbook_url": "",
            }
        )

        self.assertEqual(
            rendered,
            "\n".join(
                [
                    "VPN login failed",
                    "What happened: A VPN login failed.",
                    "Facts: User: atharva.kale\nSource IP: 107.197.154.253",
                    "Decision: Decide whether the login was expected.",
                    "Next steps: 1. Confirm the login was expected.\n2. Investigate if it was not.",
                    "Why it matters: This may indicate credential abuse.",
                    "Evidence: AUTH_FAILED",
                    "Monitoring: OpenVPN authentication log",
                ]
            ),
        )

    def test_catalog_exposes_content_contract_metadata_for_each_event(self):
        events = [event for module in NOTIFICATION_CATALOG for event in module["events"]]

        self.assertTrue(events)
        for event in events:
            self.assertIn(event["content_status"], {"generic", "rolled_out"})
            self.assertTrue(event["content_fields"])
            self.assertIsInstance(event["preview_sample"], dict)

    def test_approved_modules_have_unique_event_contracts(self):
        for module_key in ("vpn.openvpn", "ec2.host", "aws.rds", "ecs.probe", "aws.iam", "aws.s3"):
            module = next(item for item in NOTIFICATION_CATALOG if item["key"] == module_key)
            events = module["events"]
            self.assertTrue(all(item["content_status"] == "rolled_out" for item in events), module_key)
            self.assertTrue(all(item["defaults"].get("decision") for item in events), module_key)
            self.assertEqual(len({item["defaults"]["what_happened"] for item in events}), len(events), module_key)
            self.assertEqual(len({item["defaults"]["next_steps"] for item in events}), len(events), module_key)

    def test_next_module_event_guidance_is_specific(self):
        service = next(item for item in NOTIFICATION_CATALOG if item["key"] == "ecs.probe")
        self.assertIn("{consecutive_failures}", next(event for event in service["events"] if event["key"] == "service.down")["available_fields"])
        self.assertIn("{last_report}", next(event for event in service["events"] if event["key"] == "probe.agent.stale")["available_fields"])
        iam = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.iam")
        self.assertIn("{event_name}", iam["events"][0]["available_fields"])
        s3 = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.s3")
        self.assertIn("{operation}", next(event for event in s3["events"] if event["key"] == "s3.object.access")["available_fields"])

    def test_vpn_session_end_is_profiled(self):
        session_end = next(
            event
            for module in NOTIFICATION_CATALOG
            for event in module["events"]
            if event["key"] == "vpn.session.end"
        )
        self.assertIn("last observed", session_end["defaults"]["facts"].lower())
        self.assertIn("session trail", session_end["defaults"]["recovery"].lower())

    def test_advanced_template_remains_authoritative(self):
        profile = normalize_profile(
            {
                "module": "vpn.openvpn",
                "event_kind": "vpn.auth.failure",
                "advanced_template": "CUSTOM {{ event.actor.principal }}",
            }
        )

        self.assertEqual(
            profile["message_template"],
            "CUSTOM {{ event.actor.principal }}",
        )

    def test_vpn_failure_preview_uses_realistic_module_facts(self):
        profile = normalize_profile(
            {
                "module": "vpn.openvpn",
                "event_kind": "vpn.auth.failure",
                "severities": ["high"],
            }
        )
        self.assertIn("event.actor.principal", profile["message_template"])
        self.assertIn("event.actor.source_ip", profile["message_template"])
        self.assertIn("VPN server", profile["message_template"])
        self.assertIn("Next steps", profile["message_template"])

    def test_vpn_failure_is_marked_as_rolled_out(self):
        vpn = next(module for module in NOTIFICATION_CATALOG if module["key"] == "vpn.openvpn")
        failure = next(event for event in vpn["events"] if event["key"] == "vpn.auth.failure")

        self.assertEqual(failure["content_status"], "rolled_out")
        self.assertIn("principal", failure["preview_sample"])
        self.assertIn("source_ip", failure["preview_sample"])

    def test_preview_event_uses_the_selected_event_sample(self):
        profile = normalize_profile(
            {
                "module": "vpn.openvpn",
                "event_kind": "vpn.auth.failure",
            }
        )
        event = build_preview_event(profile)

        self.assertEqual(event.actor.principal, "atharva.kale")
        self.assertEqual(event.actor.source_ip, "107.197.154.253")
        self.assertEqual(event.target.name, "VPN server vpn-1")
        self.assertEqual(event.extra["message"], "VPN authentication FAILED")

    def test_module_rollout_defaults_are_specific_and_have_no_filler(self):
        for module in NOTIFICATION_CATALOG:
            event = module["events"][0]
            if event["content_status"] != "rolled_out":
                continue
            content = event["defaults"]
            self.assertTrue(content["why_it_matters"], module["key"])
            self.assertTrue(content["next_steps"], module["key"])
            self.assertTrue(content["monitoring_method"], module["key"])
            content_text = " ".join(str(value) for value in content.values())
            self.assertNotIn("Impact depends", content_text)
            self.assertNotIn("sample evidence", content_text.lower())


if __name__ == "__main__":
    unittest.main()
