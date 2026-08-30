from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Source, Target
from blackwatch.modules.aws_cloudtrail import AwsCloudTrailAdapter
from blackwatch.modules.base import IngestContext
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, normalize_profile


EFS_EVENTS = {
    "efs.filesystem.create",
    "efs.filesystem.policy.delete",
    "efs.filesystem.policy.put",
    "efs.mount_target.create",
    "efs.mount_target.delete",
    "efs.mount_target.sg.modify",
    "efs.filesystem.delete",
}


def _profile(action):
    return normalize_profile({"module": "aws.efs", "event_kind": action})


def _event(action, **extra):
    return Event(
        source=Source(module="aws.cloudtrail", account="111111111111", region="us-east-1"),
        category=Category.storage,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(principal="arn:aws:iam::111111111111:user/operator"),
        target=Target(id="fs-0123456789abcdef0", type="aws.efs", name="prod-files"),
        extra=extra,
    )


def _cloudtrail(event_name, request, response=None):
    return {
        "eventName": event_name,
        "eventSource": "elasticfilesystem.amazonaws.com",
        "eventTime": "2026-08-29T10:00:00Z",
        "awsRegion": "us-east-1",
        "sourceIPAddress": "198.51.100.20",
        "userIdentity": {"type": "IAMUser", "userName": "operator", "arn": "arn:aws:iam::111111111111:user/operator"},
        "requestParameters": request,
        "responseElements": response or {},
        "eventID": "efs-test-event-1",
    }


class Bw026EfsNotificationTests(unittest.TestCase):
    def test_catalog_covers_every_efs_event_with_unique_rolled_out_contract(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.efs")
        events = {item["key"]: item for item in module["events"]}
        self.assertEqual(set(events), EFS_EVENTS)
        self.assertTrue(all(item["content_status"] == "rolled_out" for item in events.values()))
        self.assertEqual(module["content_gap_count"], 0)
        self.assertEqual(len({item["defaults"]["title"] for item in events.values()}), len(EFS_EVENTS))
        self.assertEqual(module_for_event_kind("efs.mount_target.delete"), "aws.efs")

    def test_cloudtrail_normalizes_filesystem_mount_and_policy_fields(self):
        cases = {
            "PutFileSystemPolicy": {"fileSystemId": "fs-0123456789abcdef0", "policy": '{"Statement":[{"Effect":"Allow","Principal":"*"}]}'},
            "CreateMountTarget": {"fileSystemId": "fs-0123456789abcdef0", "subnetId": "subnet-123", "ipAddress": "10.0.2.15"},
            "ModifyMountTargetSecurityGroups": {"mountTargetId": "fsmt-123", "securityGroups": ["sg-1", "sg-2"]},
            "DeleteMountTarget": {"mountTargetId": "fsmt-123", "fileSystemId": "fs-0123456789abcdef0"},
            "DeleteFileSystem": {"fileSystemId": "fs-0123456789abcdef0"},
        }
        expected_actions = {
            "PutFileSystemPolicy": "efs.filesystem.policy.put",
            "CreateMountTarget": "efs.mount_target.create",
            "ModifyMountTargetSecurityGroups": "efs.mount_target.sg.modify",
            "DeleteMountTarget": "efs.mount_target.delete",
            "DeleteFileSystem": "efs.filesystem.delete",
        }
        for name, request in cases.items():
            event = AwsCloudTrailAdapter().parse(_cloudtrail(name, request), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
            self.assertEqual(event.action, expected_actions[name])
            if request.get("fileSystemId") or request.get("filesystemId"):
                self.assertEqual(event.extra.get("efs_filesystem_id"), "fs-0123456789abcdef0")
        mount = AwsCloudTrailAdapter().parse(_cloudtrail("CreateMountTarget", cases["CreateMountTarget"], {"mountTargetId": "fsmt-new"}), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(mount.extra.get("efs_mount_target_id"), "fsmt-new")
        self.assertEqual(mount.extra.get("efs_subnet_id"), "subnet-123")
        sg = AwsCloudTrailAdapter().parse(_cloudtrail("ModifyMountTargetSecurityGroups", cases["ModifyMountTargetSecurityGroups"]), IngestContext(module="aws.cloudtrail", transport="queue"))[0]
        self.assertEqual(sg.extra.get("efs_security_groups"), ["sg-1", "sg-2"])

    def test_policy_and_availability_events_have_deliberate_distinct_actions(self):
        templates = {action: _profile(action)["message_template"] for action in EFS_EVENTS}
        self.assertIn("policy", templates["efs.filesystem.policy.put"].lower())
        self.assertIn("restore", templates["efs.filesystem.policy.delete"].lower())
        self.assertIn("mount target", templates["efs.mount_target.delete"].lower())
        self.assertIn("filesystem", templates["efs.filesystem.delete"].lower())
        self.assertNotEqual(templates["efs.filesystem.policy.put"], templates["efs.mount_target.delete"])

    def test_complete_events_render_actionable_email_plain_text_and_chat(self):
        fixtures = {
            "efs.filesystem.policy.put": {"efs_filesystem_id": "fs-1", "efs_policy_summary": "Allow app role", "efs_policy_wildcard": True},
            "efs.filesystem.policy.delete": {"efs_filesystem_id": "fs-1", "efs_policy_summary": "Removed policy"},
            "efs.mount_target.create": {"efs_filesystem_id": "fs-1", "efs_mount_target_id": "mt-1", "efs_subnet_id": "subnet-1", "efs_availability_zone": "us-east-1a", "efs_ip_address": "10.0.2.15"},
            "efs.mount_target.delete": {"efs_filesystem_id": "fs-1", "efs_mount_target_id": "mt-1", "efs_availability_zone": "us-east-1a"},
            "efs.mount_target.sg.modify": {"efs_filesystem_id": "fs-1", "efs_mount_target_id": "mt-1", "efs_security_groups": ["sg-1", "sg-2"]},
            "efs.filesystem.delete": {"efs_filesystem_id": "fs-1", "efs_filesystem_name": "prod-files"},
        }
        for action, extra in fixtures.items():
            for channel_type in ("email", "slack"):
                body = channels._render(channels.Channel(name="security", type=channel_type, url=""), _event(action, **extra), _profile(action)["message_template"])
                self.assertIn(_profile(action)["message_template"].split("\n", 1)[0].split(":", 1)[0], body)
                self.assertNotIn("None", body)
                self.assertNotIn("not reported", body.lower())
            self.assertIn("Next steps", channels._render(channels.Channel(name="security", type="email", url=""), _event(action, **extra), _profile(action)["message_template"]))

    def test_partial_events_omit_unavailable_facts_and_avoid_false_recovery(self):
        for action in EFS_EVENTS:
            body = channels._render(channels.Channel(name="security", type="email", url=""), _event(action), _profile(action)["message_template"])
            self.assertNotIn("None", body)
            self.assertNotIn("not reported", body.lower())
            self.assertNotIn("automatically restored", body.lower())

    def test_guidance_preview_and_coverage_expose_efs_fields(self):
        profile = _profile("efs.mount_target.sg.modify")
        self.assertEqual(profile["module"], "aws.efs")
        catalog_event = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.efs")["events"][-2]
        for field in ("{efs_filesystem_id}", "{efs_mount_target_id}", "{efs_security_groups}", "{efs_availability_zone}"):
            self.assertIn(field, catalog_event["available_fields"])
        module = next(item for item in build_coverage([], []) if item["key"] == "aws.efs")
        self.assertEqual(module["content_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()
