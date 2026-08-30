from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Event, Source, Target
from blackwatch.notify import channels
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, normalize_profile


CERT_EVENTS = {
    "cert.expired",
    "cert.expiring.critical",
    "cert.expiring.high",
    "cert.expiring.warning",
    "cert.probe.failed",
}


def _profile(action: str) -> dict:
    return normalize_profile({"module": "cert", "event_kind": action})


def _event(action: str, **extra) -> Event:
    return Event(
        source=Source(module="cert", account="prod", region="us-east-1"),
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(),
        target=Target(id="api.example.com:443", type="tls_endpoint", name="api.example.com"),
        extra=extra,
    )


class Bw022CertificateNotificationTests(unittest.TestCase):
    def test_all_certificate_events_have_unique_rolled_out_contracts(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "cert")
        events = {item["key"]: item for item in module["events"]}

        self.assertEqual(set(events), CERT_EVENTS)
        self.assertTrue(all(item["content_status"] == "rolled_out" for item in events.values()))
        for field in ("title", "what_happened", "facts", "decision", "next_steps", "evidence", "recovery"):
            self.assertTrue(all(events[key]["defaults"].get(field) for key in events), field)
        self.assertEqual(len({item["defaults"]["title"] for item in events.values()}), 5)
        self.assertEqual(len({item["defaults"]["next_steps"] for item in events.values()}), 5)
        self.assertEqual(module["content_gap_count"], 0)

    def test_expiry_urgency_actions_are_different_and_actionable(self):
        actions = {
            action: _profile(action)["message_template"]
            for action in CERT_EVENTS - {"cert.probe.failed"}
        }

        self.assertIn("renew and deploy immediately", actions["cert.expiring.critical"].lower())
        self.assertIn("assign the renewal owner", actions["cert.expiring.high"].lower())
        self.assertIn("schedule renewal", actions["cert.expiring.warning"].lower())
        self.assertIn("probe", actions["cert.expiring.critical"].lower())
        self.assertNotEqual(actions["cert.expiring.critical"], actions["cert.expiring.high"])
        self.assertNotEqual(actions["cert.expiring.high"], actions["cert.expiring.warning"])

    def test_complete_expired_fixture_has_plain_text_golden(self):
        event = _event(
            "cert.expired",
            host="api.example.com",
            port=443,
            subject="CN=api.example.com",
            issuer="Let's Encrypt Authority X3",
            sans=["api.example.com", "www.example.com"],
            not_after="2026-08-28T00:00:00Z",
            days_remaining=-1,
        )
        rendered = channels._render(
            channels.Channel(name="security", type="email", url=""),
            event,
            _profile("cert.expired")["message_template"],
        )

        self.assertIn("Certificate expired · CN=api.example.com", rendered)
        self.assertIn("Host: api.example.com", rendered)
        self.assertIn("Port: 443", rendered)
        self.assertIn("Issuer: Let's Encrypt Authority X3", rendered)
        self.assertIn("SANs: api.example.com, www.example.com", rendered)
        self.assertIn("Days remaining: -1", rendered)
        self.assertIn("renew and deploy", rendered.lower())
        self.assertIn("What happened:", rendered)
        self.assertIn("Decision:", rendered)
        self.assertIn("Next steps:", rendered)

    def test_probe_failure_chat_is_not_described_as_expiry(self):
        event = _event("cert.probe.failed", host="api.example.com", port=443, error="TLS handshake timeout")
        rendered = channels._render(
            channels.Channel(name="security", type="slack", url=""),
            event,
            _profile("cert.probe.failed")["message_template"],
        )

        self.assertIn("Certificate probe failed", rendered)
        self.assertIn("TLS handshake timeout", rendered)
        self.assertIn("run an independent endpoint check", rendered.lower())
        self.assertNotIn("Certificate expired ·", rendered)
        self.assertNotIn("days remaining", rendered.lower())

    def test_partial_fixtures_omit_unavailable_certificate_values(self):
        for action in CERT_EVENTS:
            rendered = channels._render(
                channels.Channel(name="security", type="email", url=""),
                _event(action),
                _profile(action)["message_template"],
            )
            self.assertNotIn("None", rendered)
            self.assertNotIn("not reported", rendered.lower())
            self.assertNotIn("Issuer:", rendered)
            self.assertNotIn("SANs:", rendered)
            if action == "cert.probe.failed":
                self.assertNotIn("Evidence:", rendered)

    def test_preview_data_uses_real_certificate_extra_fields(self):
        for action in CERT_EVENTS:
            event = build_preview_event(_profile(action))
            self.assertEqual(event.action, action)
            self.assertIn("subject", event.extra)
            self.assertIn("days_remaining", event.extra)


if __name__ == "__main__":
    unittest.main()
