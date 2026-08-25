from pathlib import Path
import unittest

from blackwatch.db_safety import MigrationSafetyError, assert_migration_safe


ROOT = Path(__file__).resolve().parents[1]


class DataSafetyContractTests(unittest.TestCase):
    def test_destructive_migration_sql_is_rejected_before_execution(self):
        with self.assertRaisesRegex(MigrationSafetyError, "TRUNCATE"):
            assert_migration_safe("TRUNCATE TABLE events;")

        with self.assertRaisesRegex(MigrationSafetyError, "DROP TABLE"):
            assert_migration_safe("DROP TABLE old_events;")

        with self.assertRaisesRegex(MigrationSafetyError, "DROP COLUMN"):
            assert_migration_safe("ALTER TABLE events DROP COLUMN payload;")

    def test_all_checked_in_migrations_are_data_preserving(self):
        for path in sorted((ROOT / "blackwatch" / "sql").glob("*.sql")):
            assert_migration_safe(path.read_text(encoding="utf-8"))

    def test_compose_uses_named_postgres_storage_and_project_contract_prioritizes_data(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        contract = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("bw_pgdata:/var/lib/postgresql/data", compose)
        self.assertIn("docker compose down -v", compose)
        self.assertIn("Data preservation is the first priority", contract)


if __name__ == "__main__":
    unittest.main()
