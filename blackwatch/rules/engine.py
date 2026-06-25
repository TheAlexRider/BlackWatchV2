"""Stateless rule evaluation. Runs synchronously on ingest, mutating the event:
sets `severity`, appends `rule_matches`, and merges `tags`. Suppression rules
win over alert rules (allowlist behavior); among alert rules, highest severity
wins. Multi-event correlation/state is intentionally out of scope (Phase 3)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from ..event import Event, Severity, severity_rank
from .model import Condition, Rule
from .operators import OPERATORS


def get_field(event: Event, path: str) -> Any:
    """Resolve a dotted field path against a normalized event."""
    if path == "observables.value":
        return [o.value for o in event.observables]
    if path == "observables.type":
        return [o.type.value for o in event.observables]

    obj: Any = event
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, dict):  # allows rules to reach into extra.* etc.
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
    if isinstance(obj, Enum):
        return obj.value
    return obj


def eval_condition(cond: Condition, event: Event) -> bool:
    if cond.all is not None:
        return all(eval_condition(c, event) for c in cond.all)
    if cond.any is not None:
        return any(eval_condition(c, event) for c in cond.any)
    if cond.not_ is not None:
        return not eval_condition(cond.not_, event)
    if not cond.field or not cond.op:
        return False
    operator = OPERATORS.get(cond.op)
    if operator is None:
        raise ValueError(f"unknown operator: {cond.op!r}")
    return operator(get_field(event, cond.field), cond.value)


class RuleEngine:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules = list(rules)

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        for rule in self.rules:
            if rule.id == rule_id:
                rule.enabled = enabled
                return True
        return False

    def evaluate(self, event: Event) -> Event:
        matched = [
            r for r in self.rules if r.enabled and eval_condition(r.match, event)
        ]
        if not matched:
            return event

        event.rule_matches = [r.id for r in matched]
        tags = set(event.tags)
        for rule in matched:
            tags.update(rule.tags)

        suppressed = [r for r in matched if r.action == "suppress"]
        if suppressed:
            event.severity = Severity.informational
            tags.add("suppressed")
        else:
            best: Severity | None = None
            for rule in matched:
                if rule.severity is None:
                    continue
                if best is None or severity_rank(rule.severity) > severity_rank(best):
                    best = rule.severity
            event.severity = best

        event.tags = sorted(tags)
        return event


def load_rules(path: str | Path) -> list[Rule]:
    rules: list[Rule] = []
    seen: set[str] = set()
    base = Path(path)
    if not base.exists():
        return rules
    for rule_file in sorted([*base.glob("*.yaml"), *base.glob("*.yml")]):
        data = yaml.safe_load(rule_file.read_text(encoding="utf-8")) or []
        for item in data:
            rule = Rule(**item)
            if rule.id in seen:
                raise ValueError(f"duplicate rule id {rule.id!r} in {rule_file.name}")
            seen.add(rule.id)
            rules.append(rule)
    return rules


_engine: RuleEngine | None = None


def init_engine(path: str | Path) -> None:
    global _engine
    _engine = RuleEngine(load_rules(path))


def get_engine() -> RuleEngine:
    if _engine is None:
        return RuleEngine([])
    return _engine
