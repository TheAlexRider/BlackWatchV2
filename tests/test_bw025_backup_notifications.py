from datetime import datetime, timezone
import unittest

from blackwatch.event import Actor, Category, Event, Source, Target
from blackwatch.notify import channels
from blackwatch.notify.catalog import build_coverage, module_for_event_kind
from blackwatch.notify.profiles import NOTIFICATION_CATALOG, build_preview_event, normalize_profile


BACKUP_EVENTS = {
    "backup.vault.create",
    "backup.recovery_point.delete",
    "backup.vault.delete",
    "backup.vault.policy.delete",
    "backup.vault.policy.put",
    "backup.copy_job.start",
}


def _profile(action: str) -> dict:
    return normalize_profile({"module": "aws.backup", "event_kind": action})


def _event(action: str, **extra) -> Event:
    return Event(
        source=Source(module="aws.cloudtrail", account="prod", region="us-east-1"),
        category=Category.storage,
        action=action,
        event_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
        actor=Actor(principal="arn:aws:iam::111111111111:user/operator"),
        target=Target(id="arn:aws:backup:us-east-1:111111111111:vault:critical", type="backup_vault", name="critical"),
        extra=extra,
    )


class Bw025BackupNotificationTests(unittest.TestCase):
    def test_catalog_has_unique_rolled_out_contract_for_every_backup_event(self):
        module = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.backup")
        events = {item["key"]: item for item in module["events"]}
        self.assertEqual(set(events), BACKUP_EVENTS)
        self.assertTrue(all(item["content_status"] == "rolled_out" for item in events.values()))
        self.assertEqual(module["content_gap_count"], 0)
        self.assertEqual(module_for_event_kind("backup.copy_job.start"), "aws.backup")
        self.assertEqual(len({item["defaults"]["title"] for item in events.values()}), len(BACKUP_EVENTS))

    def test_deletion_and_copy_contracts_use_distinct_urgent_decisions(self):
        templates = {action: _profile(action)["message_template"] for action in BACKUP_EVENTS}
        self.assertIn("last known-good recovery point", templates["backup.recovery_point.delete"].lower())
        self.assertIn("retention", templates["backup.vault.delete"].lower())
        self.assertIn("do not", templates["backup.recovery_point.delete"].lower())
        self.assertIn("cross-account", templates["backup.copy_job.start"].lower())
        self.assertNotEqual(templates["backup.vault.policy.delete"], templates["backup.vault.policy.put"])

    def test_complete_recovery_point_deletion_email_and_chat_are_actionable(self):
        event = _event(
            "backup.recovery_point.delete",
            recovery_point_arn="arn:aws:backup:us-east-1:111111111111:recovery-point:rp-42",
            resource_arn="arn:aws:rds:us-east-1:111111111111:db:prod",
            recovery_point_time="2026-08-28T03:00:00Z",
            retention_days=35,
            vault_name="critical",
            plan_name="nightly-prod",
            deletion_protection="not reported",
        )
        for channel_type in ("email", "slack"):
            body = channels._render(channels.Channel(name="security", type=channel_type, url=""), event, _profile(event.action)["message_template"])
            self.assertIn("Backup recovery point deleted", body)
            self.assertIn("rp-42", body)
            self.assertIn("last known-good", body.lower())
            self.assertIn("manual", body.lower())
            self.assertIn("no automatic recovery", body.lower())

    def test_partial_backup_events_omit_unavailable_facts_and_recovery_claims(self):
        for action in BACKUP_EVENTS:
            body = channels._render(
                channels.Channel(name="security", type="email", url=""),
                _event(action),
                _profile(action)["message_template"],
            )
            self.assertNotIn("None", body)
            self.assertNotIn("not reported", body.lower())
            if action != "backup.vault.create":
                self.assertNotIn("Recovery point:", body)
                self.assertNotIn("Vault:", body)
            self.assertNotIn("automatically restored", body.lower())

    def test_copy_preview_and_field_guidance_expose_provider_facts(self):
        profile = _profile("backup.copy_job.start")
        preview = build_preview_event(profile)
        self.assertEqual(preview.action, "backup.copy_job.start")
        for field in ("job_id", "destination_vault_arn", "destination_account", "destination_region"):
            self.assertIn(field, preview.extra)
        event = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.backup")["events"][-1]
        self.assertIn("{job_id}", event["available_fields"])
        coverage = next(item for item in build_coverage([], []) if item["key"] == "aws.backup")
        self.assertEqual(coverage["content_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()
