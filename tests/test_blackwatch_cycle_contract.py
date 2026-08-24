import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from validate_blackwatch_cycle import validate  # noqa: E402


class BlackWatchCycleContractTests(unittest.TestCase):
    def test_repository_has_a_valid_blackwatch_cycle_contract(self):
        self.assertEqual(validate(PROJECT_ROOT), [])

    def test_task_template_starts_gated(self):
        task = (PROJECT_ROOT / ".blackwatch" / "templates" / "task.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("status: proposed", task)
        self.assertIn("implementation_allowed: false", task)
        self.assertIn("approved_by: null", task)

    def test_cycle_template_blocks_coding(self):
        cycle = json.loads(
            (PROJECT_ROOT / ".blackwatch" / "templates" / "cycle.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(cycle["trigger"], "BLACKWATCH CYCLE")
        self.assertEqual(
            cycle["roles"]["coding"]["status"],
            "blocked_until_explicit_approval",
        )

    def test_root_contract_contains_required_gates(self):
        instructions = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for required_text in (
            "BLACKWATCH CYCLE",
            "IMPLEMENT BW-###",
            "implementation_allowed: false",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, instructions)


if __name__ == "__main__":
    unittest.main()
