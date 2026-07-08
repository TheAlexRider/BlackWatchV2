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


def test_noise_mute_action_only(monkeypatch):
    """Bare-action mute (no filters) drops every event with the matching
    action, regardless of source_type / username / reason."""
    monkeypatch.setattr(
        noise, "_muted", [noise.MuteRule(action="auth.assume_role")],
    )
    assert noise.is_muted(
        Event(source=Source(module="aws.cloudtrail"), action="auth.assume_role"),
    ) is True
    assert noise.is_muted(
        Event(source=Source(module="aws.cloudtrail"), action="iam.policy.attach"),
    ) is False


def test_noise_mute_contextual(monkeypatch):
    """When source_type / username / reason are set on the rule, the mute
    only fires for events whose extra fields match ALL of them."""
    monkeypatch.setattr(
        noise, "_muted",
        [noise.MuteRule(
            action="rds.auth.failure",
            source_type="postgres",
            username="application_user",
            reason="no_pg_hba_entry",
        )],
    )
    matching = Event(
        source=Source(module="aws.rds"),
        action="rds.auth.failure",
        extra={
            "source_type": "postgres",
            "user": "application_user",
            "reason": "no_pg_hba_entry",
        },
    )
    assert noise.is_muted(matching) is True

    # Different reason on same action -> not muted (real password failure
    # for the same user still fires).
    other_reason = Event(
        source=Source(module="aws.rds"),
        action="rds.auth.failure",
        extra={
            "source_type": "postgres",
            "user": "application_user",
            "reason": "invalid_password",
        },
    )
    assert noise.is_muted(other_reason) is False

    # Different user on same action -> not muted.
    other_user = Event(
        source=Source(module="aws.rds"),
        action="rds.auth.failure",
        extra={
            "source_type": "postgres",
            "user": "haritha_desetty",
            "reason": "no_pg_hba_entry",
        },
    )
    assert noise.is_muted(other_user) is False


def test_noise_muted_events_view(monkeypatch):
    monkeypatch.setattr(
        noise, "_muted", [noise.MuteRule(action="auth.assume_role")],
    )
    assert noise.muted_events() == [{
        "action": "auth.assume_role",
        "source_type": None,
        "username": None,
        "reason": None,
    }]
