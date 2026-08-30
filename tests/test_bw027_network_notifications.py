from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Severity, Source, Target
from blackwatch.modules.aws_cloudtrail import AwsCloudTrailAdapter
from blackwatch.modules.aws_cloudtrail import _ACTION_MAP
from blackwatch.modules.base import IngestContext
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, normalize_profile


NETWORK_EVENTS = {
    "network.igw.attach",
    "network.peering.accept",
    "network.tgw_peering.accept",
    "network.sg.ingress.add",
}


def _profile(action):
    return normalize_profile({"module": "aws.network", "event_kind": action})


def _event(action, **extra):
    return Event(
        source=Source(module="aws.cloudtrail", vendor="aws", account="111111111111", region="us-east-1"),
        category=Category.network,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(principal="arn:aws:iam::111111111111:user/operator", source_ip="198.51.100.20"),
        target=Target(id=extra.pop("target_id", "resource-1"), type="aws.ec2"),
        extra=extra,
    )


def _cloudtrail(event_name, request, response=None):
    return {
        "eventName": event_name,
        "eventSource": "ec2.amazonaws.com",
        "eventTime": "2026-08-29T10:00:00Z",
        "awsRegion": "us-east-1",
        "sourceIPAddress": "198.51.100.20",
        "recipientAccountId": "111111111111",
        "userIdentity": {"type": "IAMUser", "userName": "operator", "arn": "arn:aws:iam::111111111111:user/operator"},
        "requestParameters": request,
        "responseElements": response or {},
        "eventID": "network-test-event-1",
    }


class Bw027NetworkNotificationTests(unittest.TestCase):
    def test_network_producer_actions_are_explicitly_classified(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.network")
        inventory = module.get("producer_event_inventory") or {}
        catalog_events = {item["key"] for item in module["events"]}
        producer_actions = {
            normalized_action for normalized_action, category in _ACTION_MAP.values()
            if category is Category.network
        }
        classified = catalog_events | set(inventory)
        self.assertEqual(producer_actions, classified)
        self.assertEqual(
            {action for action in inventory if action not in catalog_events},
            set(inventory),
        )
        self.assertTrue(all(value.startswith("future: non-notifying") for value in inventory.values()))

    def test_catalog_covers_all_network_events_with_unique_rolled_out_contracts(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.network")
        events = {item["key"]: item for item in module["events"]}
        self.assertEqual(set(events), NETWORK_EVENTS)
        self.assertTrue(all(item["content_status"] == "rolled_out" for item in events.values()))
        self.assertEqual(module["content_gap_count"], 0)
        self.assertEqual(len({item["defaults"]["title"] for item in events.values()}), len(NETWORK_EVENTS))
        self.assertEqual(module_for_event_kind("network.sg.ingress.add"), "aws.network")

    def test_cloudtrail_normalizes_provider_fields_for_each_network_event(self):
        cases = {
            "AttachInternetGateway": ({"internetGatewayId": "igw-123", "vpcId": "vpc-123"}, "network.igw.attach"),
            "AcceptVpcPeeringConnection": ({"vpcPeeringConnectionId": "pcx-123"}, "network.peering.accept"),
            "AcceptTransitGatewayPeeringAttachment": ({"transitGatewayAttachmentId": "tgw-attach-123"}, "network.tgw_peering.accept"),
            "AuthorizeSecurityGroupIngress": ({
                "groupId": "sg-123",
                "ipPermissions": {"items": [{"ipProtocol": "tcp", "fromPort": 22, "toPort": 22, "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]}}]},
            }, "network.sg.ingress.add"),
        }
        for name, (request, action) in cases.items():
            event = AwsCloudTrailAdapter().parse(_cloudtrail(name, request), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
            self.assertEqual(event.action, action)
            self.assertEqual(event.source.account, "111111111111")
            self.assertEqual(event.source.region, "us-east-1")
        igw = AwsCloudTrailAdapter().parse(_cloudtrail("AttachInternetGateway", cases["AttachInternetGateway"][0]), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(igw.extra["vpc_id"], "vpc-123")
        self.assertEqual(igw.extra["gateway_id"], "igw-123")
        peering = AwsCloudTrailAdapter().parse(_cloudtrail("AcceptVpcPeeringConnection", cases["AcceptVpcPeeringConnection"][0], {"vpcPeeringConnection": {"requesterVpcInfo": {"vpcId": "vpc-a", "ownerId": "222222222222"}, "accepterVpcInfo": {"vpcId": "vpc-b", "ownerId": "111111111111"}}}), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(peering.extra["peering_id"], "pcx-123")
        self.assertEqual(peering.extra["source_account"], "222222222222")
        self.assertEqual(peering.extra["destination_account"], "111111111111")
        ingress = AwsCloudTrailAdapter().parse(_cloudtrail("AuthorizeSecurityGroupIngress", cases["AuthorizeSecurityGroupIngress"][0]), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(ingress.extra["security_group_id"], "sg-123")
        self.assertEqual(ingress.extra["protocol"], "tcp")
        self.assertEqual(ingress.extra["from_port"], 22)
        self.assertEqual(ingress.extra["to_port"], 22)
        self.assertEqual(ingress.extra["cidrs"], ["0.0.0.0/0"])
        self.assertTrue(ingress.extra["public_exposure"])
        self.assertTrue(ingress.extra["risky_exposure"])

    def test_each_event_has_an_exact_email_plain_text_golden_body(self):
        fixtures = {
            "network.igw.attach": {"gateway_id": "igw-123", "vpc_id": "vpc-123"},
            "network.peering.accept": {"peering_id": "pcx-123", "source_vpc_id": "vpc-a", "destination_vpc_id": "vpc-b", "source_account": "222222222222", "destination_account": "111111111111"},
            "network.tgw_peering.accept": {"peering_id": "tgw-attach-123", "source_account": "222222222222", "destination_account": "111111111111"},
            "network.sg.ingress.add": {"security_group_id": "sg-123", "protocol": "tcp", "from_port": 22, "to_port": 22, "port_range": "22", "cidrs": ["0.0.0.0/0"], "public_exposure": True, "risky_exposure": True, "exposure_summary": "yes · risky"},
        }
        expected = {
            "network.igw.attach": """Internet gateway attached
What happened: An internet gateway was attached to a VPC, creating a potential internet path.
Facts: Gateway: igw-123
VPC: vpc-123
Account: 111111111111
Region: us-east-1
When: 2026-08-29T10:00:00Z
Decision: Confirm the VPC is intended to have internet connectivity and the attachment is approved.
Next steps: Validate route tables and public subnets; confirm the owner and change ticket; check for newly reachable workloads; detach through the approved process if unauthorized.
Why it matters: An internet gateway can expose a VPC when routes and public addressing permit it.
Evidence: CloudTrail supplied the network identifiers and provider fields shown above when available.
Monitoring: AWS CloudTrail VPC, peering, transit-gateway, and security-group events.
Impact: Connectivity or exposure may have changed; exposure is not inferred without route validation.
Recovery: No automatic recovery is claimed; manual resolution requires an approved network change followed by connectivity and exposure validation.""",
            "network.peering.accept": """VPC peering accepted
What happened: A VPC peering request was accepted, creating a potential cross-VPC path.
Facts: Peering: pcx-123
Source VPC: vpc-a
Destination VPC: vpc-b
Source account: 222222222222
Destination account: 111111111111
When: 2026-08-29T10:00:00Z
Decision: Confirm both VPC owners approved the peering and that routes and security groups allow only intended connectivity.
Next steps: Validate both accounts and owners; review routes, DNS, and security-group reachability; confirm the change ticket; delete the peering through the approved process if unauthorized.
Why it matters: Peering can bypass assumptions that the two VPCs are isolated.
Evidence: CloudTrail supplied the network identifiers and provider fields shown above when available.
Monitoring: AWS CloudTrail VPC, peering, transit-gateway, and security-group events.
Impact: Cross-VPC connectivity may be available; actual reachability depends on routes and controls.
Recovery: No automatic recovery is claimed; manual resolution requires an approved network change followed by connectivity and exposure validation.""",
            "network.tgw_peering.accept": """Transit gateway peering accepted
What happened: A transit gateway peering request was accepted, creating a potential routed cross-network path.
Facts: Attachment: tgw-attach-123
Source account: 222222222222
Destination account: 111111111111
When: 2026-08-29T10:00:00Z
Decision: Confirm both gateway owners approved the connection and that route propagation is intentional.
Next steps: Verify gateway owners and change ticket; review propagated routes and reachable CIDRs; test only intended connectivity; delete the peering through the approved process if unauthorized.
Why it matters: Transit-gateway peering can expand the blast radius of a route mistake across multiple networks.
Evidence: CloudTrail supplied the network identifiers and provider fields shown above when available.
Monitoring: AWS CloudTrail VPC, peering, transit-gateway, and security-group events.
Impact: Additional routed networks may become reachable; actual exposure depends on route propagation and controls.
Recovery: No automatic recovery is claimed; manual resolution requires an approved network change followed by connectivity and exposure validation.""",
            "network.sg.ingress.add": """Security-group ingress rule added
What happened: An inbound security-group rule was added.
Facts: Security group: sg-123
Protocol: tcp
Ports: 22
CIDRs: 0.0.0.0/0
Public exposure: yes · risky
When: 2026-08-29T10:00:00Z
Decision: Confirm the rule provides only intended connectivity; treat public or risky exposure as unauthorized until proven otherwise.
Next steps: Validate CIDR, protocol, and ports against the design; confirm owner and ticket; test intended connectivity and public reachability; revoke through the approved process if unnecessary.
Why it matters: Ingress rules directly define who can reach a workload.
Evidence: CloudTrail supplied the network identifiers and provider fields shown above when available.
Monitoring: AWS CloudTrail VPC, peering, transit-gateway, and security-group events.
Impact: Inbound reachability changed; public or risky exposure is called out only when supported by the provider rule.
Recovery: No automatic recovery is claimed; manual resolution requires an approved network change followed by connectivity and exposure validation.""",
        }
        for action, extra in fixtures.items():
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action, **extra), _profile(action)["message_template"])
            self.assertEqual(body, expected[action])
            self.assertEqual(body, body.strip())
            self.assertNotIn("None", body)
            self.assertNotIn("not reported", body.lower())
            self.assertIn("What happened:", body)
            self.assertIn("Facts:", body)
            self.assertIn("Decision:", body)
            self.assertIn("Next steps:", body)
            self.assertIn("Evidence:", body)
            self.assertIn("Recovery:", body)

    def test_each_event_has_exact_chat_body_distinct_from_generic_action(self):
        fixtures = {
            "network.igw.attach": {"gateway_id": "igw-123", "vpc_id": "vpc-123"},
            "network.peering.accept": {"peering_id": "pcx-123", "source_vpc_id": "vpc-a", "destination_vpc_id": "vpc-b", "source_account": "222222222222", "destination_account": "111111111111"},
            "network.tgw_peering.accept": {"peering_id": "tgw-attach-123", "source_account": "222222222222", "destination_account": "111111111111"},
            "network.sg.ingress.add": {"security_group_id": "sg-123", "protocol": "tcp", "from_port": 22, "to_port": 22, "port_range": "22", "cidrs": ["0.0.0.0/0"], "public_exposure": True, "risky_exposure": True, "exposure_summary": "yes · risky"},
        }
        for action, extra in fixtures.items():
            body = channels._render(channels.Channel(name="security", type="slack", url=""), _event(action, **extra), _profile(action)["message_template"])
            self.assertEqual(body, channels._render(channels.Channel(name="security", type="email", url=""), _event(action, **extra), _profile(action)["message_template"]))
            self.assertNotEqual(body, action)
            self.assertNotIn("unknown", body.lower())

    def test_slack_sender_builds_a_real_severity_payload(self):
        event = _event("network.sg.ingress.add", security_group_id="sg-123").model_copy(update={"severity": Severity.high})
        body = channels._render(
            channels.Channel(name="security", type="slack", url=""),
            event,
            _profile(event.action)["message_template"],
        )
        captured = {}

        def capture(url, payload, timeout=10):
            captured.update({"url": url, "payload": payload, "timeout": timeout})
            return True, "HTTP 200"

        original = channels._post_json
        try:
            channels._post_json = capture
            result = channels._send_slack({"url": "https://hooks.slack.test"}, body, event)
        finally:
            channels._post_json = original

        self.assertEqual(result, (True, "HTTP 200"))
        attachment = captured["payload"]["attachments"][0]
        self.assertEqual(captured["url"], "https://hooks.slack.test")
        self.assertEqual(attachment["color"], "#FB923C")
        self.assertEqual(attachment["mrkdwn_in"], ["text"])
        self.assertEqual(attachment["footer"], "BlackWatch · high")
        self.assertEqual(attachment["ts"], int(event.event_time.timestamp()))
        self.assertIn("Security-group ingress rule added", attachment["text"])

    def test_cloudtrail_event_renders_through_network_contract(self):
        raw = _cloudtrail(
            "AuthorizeSecurityGroupIngress",
            {
                "groupId": "sg-live",
                "ipPermissions": {"items": [{
                    "ipProtocol": "tcp",
                    "fromPort": 443,
                    "toPort": 443,
                    "ipRanges": {"items": [{"cidrIp": "203.0.113.0/24"}]},
                }]},
            },
        )
        event = AwsCloudTrailAdapter().parse(raw, IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        body = channels._render(
            channels.Channel(name="security", type="email", url=""),
            event,
            _profile(event.action)["message_template"],
        )
        self.assertEqual(event.action, "network.sg.ingress.add")
        self.assertIn("Security group: sg-live", body)
        self.assertIn("Ports: 443", body)
        self.assertIn("Protocol: tcp", body)
        self.assertIn("Next steps:", body)

    def test_partial_events_omit_unavailable_facts_and_claim_manual_follow_up(self):
        for action in NETWORK_EVENTS:
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action), _profile(action)["message_template"])
            self.assertNotIn("None", body)
            self.assertNotIn("unknown", body.lower())
            self.assertNotIn("automatically", body.lower())
            self.assertIn("manual", body.lower())

    def test_guidance_preview_and_coverage_expose_network_fields(self):
        profile = _profile("network.sg.ingress.add")
        module_catalog = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.network")
        catalog_event = next(item for item in module_catalog["events"] if item["key"] == "network.sg.ingress.add")
        for field in ("{vpc_id}", "{gateway_id}", "{peering_id}", "{protocol}", "{from_port}", "{to_port}", "{cidrs}", "{public_exposure}"):
            self.assertIn(field, catalog_event["available_fields"])
        self.assertTrue(catalog_event["preview_sample"]["extra"])
        module = next(item for item in build_coverage([], []) if item["key"] == "aws.network")
        self.assertEqual(module["content_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()
