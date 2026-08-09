"""UEBA baseline / first-seen anomaly checks.

Warm-up: first sighting silently populates, no anomaly emitted.
Post-warm-up: a new dimension value fires exactly one anomaly.
Replay: re-running the same trigger event does not emit a duplicate."""

from datetime import datetime, timedelta, timezone

import pytest

from blackwatch.event import Actor, ActorType, Category, Event, Outcome, Source
from blackwatch.ueba import check as ueba_check
from blackwatch.ueba import config as ueba_config
from blackwatch.ueba import db as ueba_db


def _mk(ts: datetime, ip: str, action: str = "iam.role.assume") -> Event:
    return Event(
        source=Source(module="aws.iam"),
        event_time=ts,
        category=Category.iam,
        action=action,
        outcome=Outcome.success,
        actor=Actor(principal="alice", type=ActorType.user, source_ip=ip),
    )


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    ueba_db.set_db_path(str(tmp_path / "baseline.db"))
    # force config reload with defaults (no rules/ueba.yaml assumed)
    monkeypatch.setattr(ueba_config, "_cached", None)
    monkeypatch.setattr(ueba_config, "_cached_mtime", None)
    yield


def test_warmup_then_first_seen(fresh_db):
    emitted: list[Event] = []
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    # First event: populates baseline silently — no anomaly during warm-up.
    ueba_check.check_event(_mk(t0, "1.1.1.1"), emitted.append)
    assert emitted == []

    # Fast-forward past the 7-day warm-up window; new IP appears -> one anomaly.
    t1 = t0 + timedelta(days=8)
    ueba_check.check_event(_mk(t1, "2.2.2.2"), emitted.append)

    first_seen_ip = [
        e for e in emitted if e.action == "iam.anomaly.first_seen_source_ip"
    ]
    assert len(first_seen_ip) == 1
    anom = first_seen_ip[0]
    assert anom.extra["baseline_value"] == "2.2.2.2"
    assert anom.extra["principal_id"] == "alice"
    assert anom.extra["dimension"] == "source_ip"

    # Replay same second event: baseline count becomes >1, no new anomaly.
    before = len(emitted)
    ueba_check.check_event(_mk(t1, "2.2.2.2"), emitted.append)
    same_dim = [
        e for e in emitted[before:] if e.action == "iam.anomaly.first_seen_source_ip"
    ]
    assert same_dim == []


def test_no_actor_skipped(fresh_db):
    emitted: list[Event] = []
    evt = Event(
        source=Source(module="aws.iam"),
        category=Category.iam,
        action="iam.system.tick",
        actor=Actor(),  # no principal, no type
    )
    ueba_check.check_event(evt, emitted.append)
    assert emitted == []


def test_synthetic_anomaly_is_not_rechecked(fresh_db):
    emitted: list[Event] = []
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    evt = Event(
        source=Source(module="aws.iam"),
        event_time=t,
        category=Category.iam,
        action="iam.anomaly.first_seen_source_ip",
        actor=Actor(principal="alice", type=ActorType.user, source_ip="9.9.9.9"),
    )
    ueba_check.check_event(evt, emitted.append)
    assert emitted == []
    # baseline should be untouched
    assert ueba_db.query_baselines(principal_id="alice") == []
