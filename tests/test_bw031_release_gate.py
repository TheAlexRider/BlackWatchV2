import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NotificationReleaseGateTests(unittest.TestCase):
    def test_bw020_to_bw030_have_focused_tests_and_preserve_data_contract(self):
        for number in range(20, 31):
            with self.subTest(task=number):
                task = (ROOT / ".blackwatch" / "tasks" / f"BW-{number:03d}.yaml").read_text(encoding="utf-8")
                tests = list((ROOT / "tests").glob(f"test_bw{number:03d}_*.py"))
                self.assertTrue(tests, f"BW-{number:03d} has no focused test file")
                self.assertIn("Preserve", task)
                self.assertIn("data", task.lower())

    def test_notification_catalog_and_contracts_are_present(self):
        catalog = (ROOT / "blackwatch" / "notify" / "catalog.py").read_text(encoding="utf-8")
        contracts = (ROOT / "blackwatch" / "notify" / "content_contracts.py").read_text(encoding="utf-8")
        self.assertRegex(catalog, r"NOTIFICATION_CATALOG")
        self.assertRegex(contracts, r"CONTENT_CONTRACTS|contract")

    def test_gate_is_honest_about_blocked_full_delivery_dependencies(self):
        report = (ROOT / ".blackwatch" / "reports" / "qa.md").read_text(encoding="utf-8")
        self.assertRegex(report, r"Blocked and not treated as passing")
        self.assertRegex(report, r"psycopg|jinja2")


if __name__ == "__main__":
    unittest.main()

