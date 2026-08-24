"""Validate the repository-native BlackWatch Cycle contract.

This intentionally uses only the Python standard library so it can run before
the project virtual environment or application dependencies are available.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROLE_FILES = (
    "coordinator.md",
    "research.md",
    "qa.md",
    "coder-backend.md",
    "coder-ui.md",
    "coder-infrastructure.md",
    "coder-tests.md",
)
REQUIRED_TEXT = {
    "BLACKWATCH CYCLE": "the cycle trigger",
    "IMPLEMENT BW-###": "the implementation approval gate",
    "implementation_allowed: false": "the default implementation lock",
}
TASK_ID_PATTERN = re.compile(r"^BW-\d{3,}\.ya?ml$")


def _read(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"missing required file: {path.as_posix()}")
        return ""
    return path.read_text(encoding="utf-8")


def _check_yaml_lock(path: Path, errors: list[str]) -> None:
    content = _read(path, errors)
    if not content:
        return
    if "status: proposed" not in content:
        errors.append(f"{path.as_posix()} must default to status: proposed")
    if "implementation_allowed: false" not in content:
        errors.append(
            f"{path.as_posix()} must default to implementation_allowed: false"
        )
    if "approved_by: null" not in content:
        errors.append(f"{path.as_posix()} must default to approved_by: null")


def validate(root: Path) -> list[str]:
    """Return contract violations for a BlackWatch project root."""

    root = root.resolve()
    errors: list[str] = []
    instructions = _read(root / "AGENTS.md", errors)
    for required, description in REQUIRED_TEXT.items():
        if required not in instructions:
            errors.append(f"AGENTS.md is missing {description}: {required}")

    blackwatch_dir = root / ".blackwatch"
    _read(blackwatch_dir / "README.md", errors)
    roles_dir = blackwatch_dir / "roles"
    for role_file in ROLE_FILES:
        _read(roles_dir / role_file, errors)

    templates_dir = blackwatch_dir / "templates"
    _check_yaml_lock(templates_dir / "task.yaml", errors)

    cycle_path = templates_dir / "cycle.json"
    cycle_content = _read(cycle_path, errors)
    if cycle_content:
        try:
            cycle = json.loads(cycle_content)
        except json.JSONDecodeError as exc:
            errors.append(f"{cycle_path.as_posix()} is not valid JSON: {exc}")
        else:
            if cycle.get("trigger") != "BLACKWATCH CYCLE":
                errors.append("cycle template must use the BLACKWATCH CYCLE trigger")
            coding_status = cycle.get("roles", {}).get("coding", {}).get("status")
            if coding_status != "blocked_until_explicit_approval":
                errors.append("cycle template must block coding until explicit approval")

    for directory in (blackwatch_dir / "reports", blackwatch_dir / "tasks", blackwatch_dir / "state"):
        if not directory.is_dir():
            errors.append(f"missing artifact directory: {directory.as_posix()}")

    tasks_dir = blackwatch_dir / "tasks"
    if tasks_dir.is_dir():
        for task_path in tasks_dir.iterdir():
            if task_path.name == ".gitkeep":
                continue
            if not TASK_ID_PATTERN.match(task_path.name):
                errors.append(
                    f"task file must use a BW-###.yaml name: {task_path.as_posix()}"
                )
                continue
            content = task_path.read_text(encoding="utf-8")
            if "status: proposed" in content and "implementation_allowed: true" in content:
                errors.append(
                    f"proposed task cannot enable implementation: {task_path.as_posix()}"
                )

    return errors


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    errors = validate(root)
    if errors:
        print("BlackWatch Cycle contract: INVALID")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"BlackWatch Cycle contract: VALID ({root.resolve()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
