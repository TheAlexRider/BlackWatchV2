"""Guardrails for migrations that could remove persistent application data."""

from __future__ import annotations

import re
from pathlib import Path


class MigrationSafetyError(RuntimeError):
    """Raised when a migration contains an automatic destructive operation."""


_DESTRUCTIVE_SQL = (
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    ("DELETE FROM", re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)),
    ("DROP SCHEMA", re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE)),
    ("DROP DATABASE", re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE)),
)


def _without_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\r\n]*", "", sql)


def assert_migration_safe(sql: str, *, source: str | Path = "migration") -> None:
    """Reject migration SQL that can remove data or persistent structures.

    Schema evolution must be additive or reversible through a separately
    reviewed operator action. This check intentionally fails closed before a
    migration is sent to Postgres; comments are ignored so historical
    explanations can still describe operations that are no longer allowed.
    """
    executable_sql = _without_comments(sql)
    for label, pattern in _DESTRUCTIVE_SQL:
        match = pattern.search(executable_sql)
        if match:
            line = executable_sql.count("\n", 0, match.start()) + 1
            raise MigrationSafetyError(
                f"Refusing destructive migration {source}: {label} at line {line}. "
                "Data-preserving migrations must not remove tables, columns, or rows."
            )
