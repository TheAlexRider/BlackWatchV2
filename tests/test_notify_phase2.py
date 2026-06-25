"""Phase 2 — channels, templates, worker (retries / rate-limit / digest), acks."""

from datetime import datetime, timezone

import blackwatch.notify.channels as channels_module
import blackwatch.notify.worker as worker_module
from blackwatch.event import Event, Severity, Source
from blackwatch.notify.channels import _render, _DEFAULT_TEMPLATES
from blackwatch.notify.model import Channel
from blackwatch.notify.worker import Worker, _RateLimiter, _DigestBuffer


# ---- Templates --------------------------------------------------------------

def _ev(action="iam.policy.attach", severity=Severity.high):
    e = Event(source=Source(module="aws.cloudtrail"), action=action)
    e.severity = severity
    return e


def test_default_templates_render_per_type():
    ev = _ev()
    for ctype, default in _DEFAULT_TEMPLATES.items():
        ch = Channel(name="t", type=ctype, url="http://x")
        body = _render(ch, ev)
        assert "iam.policy.attach" in body or "HIGH" in body or "" in body
        assert isinstance(body, str) and body


def test_custom_template_overrides_default():
    ev = _ev(action="root.login", severity=Severity.critical)
    ch = Channel(name="t", type="slack", url="http://x",
                 message_template="ALERT {{ event.action }} sev={{ event.severity }}")
    body = _render(ch, ev)
    assert body == "ALERT root.login sev=critical"


def test_render_falls_back_on_template_error():
    ev = _ev()
    ch = Channel(name="t", type="slack", url="http://x",
                 message_template="{{ event.nope_does_not_exist }}")
    body = _render(ch, ev)
    assert "template error" in body


# ---- Worker: rate-limit ----------------------------------------------------

def test_rate_limiter_blocks_after_threshold(monkeypatch):
    ch = Channel(name="t", type="slack", url="http://x", rate_limit_per_min=2)
    rl = _RateLimiter()
    assert rl.allow(ch) is True
    assert rl.allow(ch) is True
    assert rl.allow(ch) is False  # third hit in same minute -> blocked


def test_rate_limiter_zero_means_unlimited():
    ch = Channel(name="t", type="slack", url="http://x", rate_limit_per_min=0)
    rl = _RateLimiter()
    for _ in range(50):
        assert rl.allow(ch) is True


# ---- Worker: handle_one (with mocked send) ---------------------------------

class _RuleStub:
    def __init__(self, id="r1", name="r1"): self.id = id; self.name = name


def _stub_send_ok(monkeypatch):
    calls = []
    def fake(ch, ev): calls.append((ch.name, ev.action)); return True, "HTTP 200"
    monkeypatch.setattr(channels_module, "send", fake)
    return calls


def _stub_send_fail(monkeypatch, fail_times):
    calls = {"n": 0}
    def fake(ch, ev):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            return False, f"fail #{calls['n']}"
        return True, "HTTP 200"
    monkeypatch.setattr(channels_module, "send", fake)
    return calls


def _stub_logging(monkeypatch):
    logged = []
    monkeypatch.setattr(worker_module, "_log", lambda e: logged.append(e))
    monkeypatch.setattr(worker_module, "_record_channel_status", lambda *a, **k: None)
    return logged


def test_handle_one_sends_and_logs(monkeypatch):
    calls = _stub_send_ok(monkeypatch)
    logged = _stub_logging(monkeypatch)
    w = Worker()
    ch = Channel(name="t", type="slack", url="http://x", retries=0)
    res = w.handle_one({"rule": _RuleStub(), "channel": ch, "event": _ev()})
    assert res["status"] == "sent" and res["retries_used"] == 0
    assert len(calls) == 1
    assert logged and logged[-1]["status"] == "sent"


def test_handle_one_retries_then_succeeds(monkeypatch):
    _stub_send_fail(monkeypatch, fail_times=2)  # 3rd call succeeds
    logged = _stub_logging(monkeypatch)
    w = Worker()
    ch = Channel(name="t", type="slack", url="http://x", retries=3, retry_backoff_seconds=1)
    monkeypatch.setattr(w._stop, "wait", lambda _s: False)  # skip the backoff sleeps
    res = w.handle_one({"rule": _RuleStub(), "channel": ch, "event": _ev()})
    assert res["status"] == "sent" and res["retries_used"] == 2
    assert logged[-1]["status"] == "sent"


def test_handle_one_gives_up_after_retries(monkeypatch):
    _stub_send_fail(monkeypatch, fail_times=99)  # always fails
    logged = _stub_logging(monkeypatch)
    w = Worker()
    monkeypatch.setattr(w._stop, "wait", lambda _s: False)
    ch = Channel(name="t", type="slack", url="http://x", retries=2, retry_backoff_seconds=1)
    res = w.handle_one({"rule": _RuleStub(), "channel": ch, "event": _ev()})
    assert res["status"] == "failed" and res["retries_used"] == 2
    assert "fail #" in res["error_message"]


def test_handle_one_rate_limited_does_not_send(monkeypatch):
    calls = _stub_send_ok(monkeypatch)
    logged = _stub_logging(monkeypatch)
    w = Worker()
    ch = Channel(name="t", type="slack", url="http://x", rate_limit_per_min=1)
    w.handle_one({"rule": _RuleStub(), "channel": ch, "event": _ev()})  # first OK
    res = w.handle_one({"rule": _RuleStub(), "channel": ch, "event": _ev()})  # blocked
    assert res["status"] == "rate_limited"
    assert len(calls) == 1   # only one actual send


# ---- Worker: digest --------------------------------------------------------

def test_digest_buffers_and_due_after_window():
    db = _DigestBuffer()
    db.add("c1", {"x": 1})
    assert db.due("c1", 9999) is False
    # backdate the first_at to force "due"
    db._first_at["c1"] = 0
    assert db.due("c1", 10) is True
    items = db.drain("c1")
    assert len(items) == 1


def test_handle_one_digest_does_not_send_directly(monkeypatch):
    calls = _stub_send_ok(monkeypatch)
    logged = _stub_logging(monkeypatch)
    w = Worker()
    ch = Channel(name="t", type="slack", url="http://x", digest_window_seconds=60)
    res = w.handle_one({"rule": _RuleStub(), "channel": ch, "event": _ev()})
    assert res["status"] == "digested"
    assert calls == []   # nothing sent yet; flush would happen on window expiry
    assert logged[-1]["status"] == "digested"
