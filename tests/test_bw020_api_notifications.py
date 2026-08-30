from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Event, Source, Target
from blackwatch.modules.aws_api_gw import AwsApiGwAdapter
from blackwatch.modules.base import IngestContext
from blackwatch.notify import channels
from blackwatch.notify.profiles import (
    NOTIFICATION_CATALOG,
    build_preview_event,
    normalize_profile,
)


API_EVENTS = {
    "api.auth.failure",
    "api.auth.burst",
    "api.error",
    "api.error.burst",
    "api.scanner_ua",
    "api.source.new",
}


def _profile(event_kind: str) -> dict:
    return normalize_profile({"module": "aws.api_gateway", "event_kind": event_kind})


def _event(action: str, **extra) -> Event:
    return Event(
        source=Source(module="aws.api_gw"),
        action=action,
        event_time=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        actor=Actor(source_ip=extra.pop("source_ip", None)),
        target=Target(id="payments", name="payments"),
        extra=extra,
    )


class Bw020ApiNotificationTests(unittest.TestCase):
    def test_adapter_preserves_absent_numeric_fields_as_none(self):
        raw = {"api_name": "payments", "events": [{"ts": 1787652000000, "message": '{"httpMethod":"GET"}'}, {"ts": 1787652000000, "message": '{"status":401,"httpMethod":"GET"}'}]}
        parsed = AwsApiGwAdapter().parse(raw, IngestContext(module="aws.api_gw", transport="queue"))
        request = next(event for event in parsed if event.action == "api.request" and event.extra["status"] is None)
        auth = next(event for event in parsed if event.action == "api.auth.failure")
        self.assertIsNone(request.extra["status"])
        self.assertEqual(auth.extra["status"], 401)
        self.assertIsNone(auth.extra["response_length"])

    def test_adapter_only_classifies_401_and_403_as_auth_failures(self):
        raw = {"api_name": "payments", "events": [
            {"ts": 1787652000000, "message": '{"status":400,"httpMethod":"GET"}'},
            {"ts": 1787652000000, "message": '{"status":401,"httpMethod":"GET"}'},
            {"ts": 1787652000000, "message": '{"status":403,"httpMethod":"GET"}'},
            {"ts": 1787652000000, "message": '{"status":404,"httpMethod":"GET"}'},
        ]}
        actions = [event.action for event in AwsApiGwAdapter().parse(raw, IngestContext(module="aws.api_gw", transport="queue"))]
        self.assertEqual(actions.count("api.auth.failure"), 2)
        self.assertEqual(actions.count("api.request"), 4)

    def test_all_api_gateway_notifications_have_unique_rolled_out_contracts(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.api_gateway")
        events = {item["key"]: item for item in module["events"]}

        self.assertEqual(set(events), API_EVENTS)
        self.assertTrue(all(item["content_status"] == "rolled_out" for item in events.values()))
        self.assertEqual(len({item["defaults"]["title"] for item in events.values()}), 6)
        self.assertEqual(len({item["defaults"]["what_happened"] for item in events.values()}), 6)
        self.assertEqual(len({item["defaults"]["decision"] for item in events.values()}), 6)
        self.assertEqual(len({item["defaults"]["next_steps"] for item in events.values()}), 6)
        self.assertTrue(all(item["defaults"]["recovery"] for item in events.values()))

    def test_api_guidance_contains_only_ingested_normalized_or_named_extra_fields(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.api_gateway")
        guidance = set(next(item for item in module["events"] if item["key"] == "api.auth.failure")["available_fields"])
        self.assertTrue({"{target_name}", "{source_ip}", "{event_time}", "{severity}"}.issubset(guidance))
        self.assertTrue({"{api_name}", "{method}", "{route_key}", "{status}", "{request_id}", "{reason}", "{error_message}"}.issubset(guidance))
        self.assertNotIn("{path}", guidance)
        self.assertNotIn("{identity_header}", guidance)
        self.assertNotIn("{threshold}", guidance)

    def test_complete_fixture_has_event_specific_email_and_chat_goldens(self):
        expected = {
            "api.auth.failure": (
                "API authentication failed for payments\n"
                "What happened: API Gateway rejected one request.\n"
                "Facts: API: payments\nSource IP: 192.0.2.10\nMethod: POST\nRoute: ANY /{proxy+}\nStatus: 401\n"
                "Reason: unauthorized\nRequest ID: req-1\nWhen: 2026-08-25T10:00:00Z\n"
                "Decision: Decide whether this request was expected; this event does not identify a user or URL path.\n"
                "Next steps: Verify the source and request context, then investigate repeated failures or protect the affected access path.\n"
                "Why it matters: A single rejected request may be benign; repeated failures can indicate misuse of an API access path.\n"
                "Evidence: The normalized API status and authentication reason are the available evidence.\n"
                "Monitoring: API Gateway access-log normalization.\n"
                "Impact: This request was rejected; broader impact is not inferred from one event.\n"
                "Recovery: No automatic recovery is claimed; a later request is separate context and requires manual resolution."
            ),
            "api.auth.burst": (
                "API authentication failure burst from 192.0.2.10\n"
                "What happened: Repeated API authentication failures reached the detector's burst condition.\n"
                "Facts: API: payments\nSource IP: 192.0.2.10\nFailures: 10\nWindow: 5 minutes\nWhen: 2026-08-25T10:00:00Z\n"
                "Decision: Treat the aggregate as suspicious until the source and activity are explained.\n"
                "Next steps: Check whether the source is an approved client or gateway, review nearby successes, and contain the source if unauthorized.\n"
                "Why it matters: A concentrated failure burst can indicate credential stuffing or a noisy client that needs correction.\n"
                "Evidence: The producer supplied the failure count and window; no additional identity or path is inferred.\n"
                "Monitoring: API Gateway authentication-failure correlation by source IP.\n"
                "Impact: Multiple requests were rejected from one source; account impact is not established by this aggregate alone.\n"
                "Recovery: No automatic recovery exists; resolve manually after source validation and containment or approval."
            ),
        }
        fixtures = {
            "api.auth.failure": _event("api.auth.failure", api_name="payments", source_ip="192.0.2.10", method="POST", route_key="ANY /{proxy+}", status=401, reason="unauthorized", request_id="req-1"),
            "api.auth.burst": _event("api.auth.burst", api_name="payments", source_ip="192.0.2.10", failure_count=10, window_minutes=5),
        }
        for action, event in fixtures.items():
            profile = _profile(action)
            body = channels._render(channels.Channel(name="email", type="email", url=""), event, profile["message_template"])
            self.assertEqual(body, expected[action])

        chat = channels._render(channels.Channel(name="security", type="slack", url=""), fixtures["api.auth.failure"], _profile("api.auth.failure")["message_template"])
        self.assertEqual(chat, expected["api.auth.failure"])

    def test_partial_fixtures_omit_unavailable_api_values(self):
        for action in API_EVENTS:
            event = _event(action)
            rendered = channels._render(channels.Channel(name="email", type="email", url=""), event, _profile(action)["message_template"])
            self.assertNotIn("unknown", rendered.lower())
            self.assertNotIn("not reported", rendered.lower())
            self.assertNotIn("Status:", rendered)
            self.assertNotIn("/{proxy+}", rendered)
            self.assertNotIn("identity_header", rendered.lower())

    def test_preview_data_is_event_specific_and_uses_named_producer_extras(self):
        for action in API_EVENTS:
            event = build_preview_event(_profile(action))
            self.assertEqual(event.action, action)
            self.assertIn("api_name", event.extra)
            self.assertNotIn("path", event.extra)
            self.assertNotIn("identity_header", event.extra)

    def test_source_preview_matches_the_derived_projection_payload(self):
        event = build_preview_event(_profile("api.source.new"))
        self.assertEqual(event.actor.source_ip, "198.51.100.20")
        self.assertEqual(event.target.name, "payments")
        self.assertEqual(
            event.extra,
            {
                "api_name": "payments",
                "source_ip": "198.51.100.20",
                "tags": {"env": "prod", "api": "payments"},
                "message": "payments: new source IP 198.51.100.20 touched the API Gateway — never seen before",
            },
        )

    def test_api_rollout_has_no_content_gaps(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.api_gateway")
        self.assertEqual(module["content_status"], "rolled_out")
        self.assertEqual(module["content_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()
