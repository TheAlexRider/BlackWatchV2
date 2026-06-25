"""Rule engine tests. Mostly inline rules; one test loads the shipped pack."""

from pathlib import Path

from blackwatch.event import Actor, Event, Observable, Severity, Source, Target
from blackwatch.rules.engine import RuleEngine, eval_condition, get_field, load_rules
from blackwatch.rules.model import Condition, Rule


def _event(**kw) -> Event:
    return Event(source=Source(module=kw.pop("module", "generic")), **kw)


def _rule(rid, **kw) -> Rule:
    kw.setdefault("match", Condition(field="action", op="equals", value="x"))
    return Rule(id=rid, **kw)


def test_no_match_leaves_severity_none():
    engine = RuleEngine([_rule("r1", severity=Severity.high)])
    ev = engine.evaluate(_event(action="something.else"))
    assert ev.severity is None
    assert ev.rule_matches == []


def test_single_match_sets_severity_and_tags():
    rule = Rule(
        id="admin",
        severity=Severity.high,
        tags=["iam"],
        match=Condition(field="action", op="equals", value="iam.policy.attach"),
    )
    engine = RuleEngine([rule])
    ev = engine.evaluate(_event(action="iam.policy.attach"))
    assert ev.severity == Severity.high
    assert ev.rule_matches == ["admin"]
    assert "iam" in ev.tags


def test_highest_severity_wins_among_alerts():
    base = Condition(field="action", op="equals", value="finding.malware.detected")
    finance = Condition(
        all=[base, Condition(field="observables.value", op="in", value=["finance-uploads"])]
    )
    engine = RuleEngine(
        [
            Rule(id="malware", severity=Severity.high, match=base),
            Rule(id="malware-finance", severity=Severity.critical, match=finance),
        ]
    )
    ev = _event(
        action="finding.malware.detected",
        observables=[Observable(type="bucket", value="finance-uploads")],
    )
    engine.evaluate(ev)
    assert ev.severity == Severity.critical
    assert set(ev.rule_matches) == {"malware", "malware-finance"}


def test_suppression_wins_over_alert():
    alert = Rule(
        id="admin",
        severity=Severity.high,
        match=Condition(field="action", op="equals", value="iam.policy.attach"),
    )
    suppress = Rule(
        id="ci-allow",
        action="suppress",
        match=Condition(field="actor.principal", op="endswith", value=":role/terraform-ci"),
    )
    engine = RuleEngine([alert, suppress])
    ev = _event(
        action="iam.policy.attach",
        actor=Actor(principal="arn:aws:iam::123:role/terraform-ci"),
    )
    engine.evaluate(ev)
    assert ev.severity == Severity.informational
    assert "suppressed" in ev.tags


def test_root_usage_is_critical():
    rule = Rule(
        id="root",
        severity=Severity.critical,
        match=Condition(field="actor.is_root", op="equals", value=True),
    )
    ev = _event(action="auth.console.login", actor=Actor(is_root=True))
    RuleEngine([rule]).evaluate(ev)
    assert ev.severity == Severity.critical


def test_cidr_operator():
    cond = Condition(field="actor.source_ip", op="cidr", value="10.0.0.0/8")
    assert eval_condition(cond, _event(actor=Actor(source_ip="10.1.2.3")))
    assert not eval_condition(cond, _event(actor=Actor(source_ip="192.168.0.1")))


def test_get_field_resolves_observables_and_enums():
    ev = _event(
        category="iam",
        observables=[Observable(type="ip", value="1.2.3.4")],
    )
    assert get_field(ev, "category") == "iam"  # enum -> value
    assert get_field(ev, "observables.value") == ["1.2.3.4"]
    assert get_field(ev, "nope.missing") is None


def test_shipped_rule_pack_loads_and_is_unique():
    rules_dir = Path(__file__).resolve().parents[1] / "rules"
    rules = load_rules(rules_dir)
    assert len(rules) >= 8
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids))  # no duplicate ids across files
