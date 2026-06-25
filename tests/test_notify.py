"""Notifier dispatch — rules matching, silence/ack/throttle. Phase 2 is async:
dispatch ENQUEUES to the worker rather than sending synchronously, so we stub
`worker.get_worker().enqueue` to capture matched (rule, channel, event) tuples
and assert on dispatch's returned status (queued/throttled/skipped/acked)."""

from datetime import datetime, timedelta, timezone

import blackwatch.notify.worker as worker_module
import blackwatch.storage as storage
from blackwatch.event import Actor, Event, Severity, Source
from blackwatch.notify.model import Channel, NotificationRule
from blackwatch.notify.router import Notifier
from blackwatch.rules.model import Condition


def _event(severity=None, action="iam.policy.attach", **kw) -> Event:
    ev = Event(source=Source(module=kw.pop("module", "aws.iam")), action=action, **kw)
    ev.severity = severity
    return ev


def _rule(rid, match, channels=("t",), enabled=True, throttle=0, silence_until=None):
    return NotificationRule(
        id=rid, name=rid, enabled=enabled, match=match,
        channels=list(channels), throttle_seconds=throttle, silence_until=silence_until,
    )


def _notifier(rules, window=300):
    chan = Channel(name="t", type="webhook", url="http://x", dedup_window_seconds=window)
    return Notifier({chan.name: chan}, rules, channel_ids={chan.name: "cid"})


def _stub_enqueue(monkeypatch):
    """Capture worker.enqueue + neutralise storage.is_fingerprint_acked."""
    queued = []
    class FakeWorker:
        def enqueue(self, item): queued.append(item)
    monkeypatch.setattr(worker_module, "get_worker", lambda: FakeWorker())
    monkeypatch.setattr(storage, "is_fingerprint_acked", lambda _fp: False)
    return queued


def test_severity_threshold_via_condition(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    rule = _rule("r1", Condition(field="severity", op="in", value=["high", "critical"]))
    notifier = _notifier([rule])
    notifier.dispatch(_event(severity=Severity.critical))
    notifier.dispatch(_event(severity=Severity.medium))   # below threshold
    notifier.dispatch(_event(severity=None))               # unscored
    assert len(queued) == 1


def test_all_clause_combines(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    match = Condition(all=[
        Condition(field="severity", op="equals", value="high"),
        Condition(field="actor.principal", op="endswith", value=":role/terraform-ci"),
    ])
    notifier = _notifier([_rule("r1", match)])
    notifier.dispatch(_event(severity=Severity.high,
                             actor=Actor(principal="arn:aws:iam::1:role/terraform-ci")))
    notifier.dispatch(_event(severity=Severity.high,
                             actor=Actor(principal="arn:aws:iam::1:role/other")))
    assert len(queued) == 1


def test_silenced_rule_skipped(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    rule = _rule("r1", Condition(field="severity", op="equals", value="critical"),
                 silence_until=datetime.now(timezone.utc) + timedelta(hours=1))
    _notifier([rule]).dispatch(_event(severity=Severity.critical))
    assert queued == []


def test_silence_expired_fires(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    rule = _rule("r1", Condition(field="severity", op="equals", value="critical"),
                 silence_until=datetime.now(timezone.utc) - timedelta(seconds=1))
    _notifier([rule]).dispatch(_event(severity=Severity.critical))
    assert len(queued) == 1


def test_disabled_rule_skipped(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    rule = _rule("r1", Condition(field="severity", op="equals", value="critical"), enabled=False)
    _notifier([rule]).dispatch(_event(severity=Severity.critical))
    assert queued == []


def test_throttle_blocks_second_dispatch_in_window(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    rule = _rule("r1", Condition(field="severity", op="equals", value="high"))
    notifier = _notifier([rule], window=300)
    ev = _event(severity=Severity.high)
    first = notifier.dispatch(ev)
    second = notifier.dispatch(ev)
    assert first[0]["status"] == "queued"
    assert second[0]["status"] == "throttled"
    assert len(queued) == 1


def test_two_rules_both_enqueue(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    r1 = _rule("r1", Condition(field="severity", op="equals", value="high"))
    r2 = _rule("r2", Condition(field="category", op="equals", value="iam"))
    notifier = _notifier([r1, r2])
    ev = _event(severity=Severity.high, action="iam.policy.attach", category="iam")
    out = notifier.dispatch(ev)
    queued_status = [o for o in out if o["status"] == "queued"]
    assert len(queued_status) == 2
    assert len(queued) == 2


def test_disabled_channel_skipped(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    chan = Channel(name="t", type="webhook", url="http://x", enabled=False)
    notifier = Notifier({chan.name: chan},
                        [_rule("r1", Condition(field="severity", op="equals", value="critical"))],
                        channel_ids={chan.name: "cid"})
    out = notifier.dispatch(_event(severity=Severity.critical))
    assert queued == []
    assert any(o.get("status") == "skipped" for o in out)


def test_acked_fingerprint_short_circuits(monkeypatch):
    queued = _stub_enqueue(monkeypatch)
    monkeypatch.setattr(storage, "is_fingerprint_acked", lambda _fp: True)
    rule = _rule("r1", Condition(field="severity", op="equals", value="critical"))
    out = _notifier([rule]).dispatch(_event(severity=Severity.critical))
    assert out == [{"status": "acked", "fingerprint": _event(severity=Severity.critical).dedup_fingerprint}]
    assert queued == []
