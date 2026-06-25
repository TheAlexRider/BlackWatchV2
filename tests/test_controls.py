"""Dashboard controls: rule enable/disable + ingest muting. No DB."""

from blackwatch import noise
from blackwatch.event import Event, Severity, Source
from blackwatch.rules.engine import RuleEngine
from blackwatch.rules.model import Condition, Rule


def _rule(rid, enabled=True):
    return Rule(
        id=rid,
        enabled=enabled,
        severity=Severity.high,
        match=Condition(field="action", op="equals", value="iam.policy.attach"),
    )


def _event():
    return Event(source=Source(module="aws.cloudtrail"), action="iam.policy.attach")


def test_disabled_rule_does_not_fire():
    engine = RuleEngine([_rule("r1")])
    ev = _event()
    engine.evaluate(ev)
    assert ev.severity == Severity.high  # enabled -> fires

    assert engine.set_enabled("r1", False) is True
    ev2 = _event()
    engine.evaluate(ev2)
    assert ev2.severity is None  # disabled -> does not fire


def test_set_enabled_unknown_rule():
    engine = RuleEngine([_rule("r1")])
    assert engine.set_enabled("nope", False) is False


def test_noise_mute(monkeypatch):
    monkeypatch.setattr(noise, "_muted", {"auth.assume_role"})
    assert noise.is_muted("auth.assume_role") is True
    assert noise.is_muted("iam.policy.attach") is False
    assert noise.muted_actions() == ["auth.assume_role"]
