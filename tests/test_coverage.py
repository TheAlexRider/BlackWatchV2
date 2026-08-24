from datetime import datetime, timedelta, timezone
import unittest

from blackwatch.coverage import build_coverage_summary


class CoverageSummaryTests(unittest.TestCase):
    NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    def test_classifies_connector_health_and_maps_modules(self):
        rows = [
            {
                "id": "healthy",
                "name": "CloudTrail",
                "type": "aws_cloudtrail_sqs",
                "enabled": True,
                "verified": True,
                "config": {"target_module": "aws.cloudtrail", "interval_seconds": 60},
                "last_run_at": self.NOW - timedelta(seconds=60),
                "last_status": "ok",
                "last_error": None,
            },
            {
                "id": "failing",
                "name": "RDS",
                "type": "aws_rds_sqs",
                "enabled": True,
                "verified": True,
                "config": {"interval_seconds": 60},
                "last_run_at": self.NOW - timedelta(seconds=60),
                "last_status": "error",
                "last_error": "queue unavailable",
            },
            {
                "id": "stale",
                "name": "Certificates",
                "type": "cert_probe",
                "enabled": True,
                "verified": True,
                "config": {"interval_seconds": 60},
                "last_run_at": self.NOW - timedelta(minutes=20),
                "last_status": "ok",
                "last_error": None,
            },
            {
                "id": "unverified",
                "name": "Posture",
                "type": "aws_posture_drift",
                "enabled": True,
                "verified": False,
                "config": {},
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
            },
            {
                "id": "disabled",
                "name": "S3",
                "type": "aws_s3_drift",
                "enabled": False,
                "verified": True,
                "config": {},
                "last_run_at": self.NOW - timedelta(days=2),
                "last_status": "ok",
                "last_error": None,
            },
        ]

        result = build_coverage_summary(rows, now=self.NOW)
        by_id = {row["connector_id"]: row for row in result["coverage"]}

        self.assertEqual(result["freshness_basis"], "connector_last_run")
        self.assertEqual(by_id["healthy"]["status"], "healthy")
        self.assertEqual(by_id["healthy"]["module"], "aws.cloudtrail")
        self.assertEqual(by_id["failing"]["status"], "failing")
        self.assertEqual(by_id["stale"]["status"], "stale")
        self.assertEqual(by_id["unverified"]["status"], "unverified")
        self.assertEqual(by_id["disabled"]["status"], "disabled")
        self.assertEqual(result["summary"]["healthy"], 1)
        self.assertEqual(result["summary"]["attention"], 3)
        self.assertEqual(result["summary"]["disabled"], 1)

    def test_successful_zero_event_run_is_not_marked_missing(self):
        result = build_coverage_summary(
            [
                {
                    "id": "collector",
                    "name": "Collector",
                    "type": "aws_s3_drift",
                    "enabled": True,
                    "verified": True,
                    "config": {"interval_seconds": 900},
                    "last_run_at": self.NOW,
                    "last_status": "ok",
                    "last_error": None,
                }
            ],
            now=self.NOW,
        )

        row = result["coverage"][0]
        self.assertEqual(row["status"], "healthy")
        self.assertEqual(row["last_seen_event"], self.NOW.isoformat())
        self.assertIn("zero events", result["zero_event_semantics"])


if __name__ == "__main__":
    unittest.main()
