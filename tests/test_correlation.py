"""Brute-force counters — sliding window, suppression, dimensional isolation.

Two parallel detectors run on every auth-failure event: per-IP and per-user.
A single trigger event can produce up to TWO derived events when both
thresholds are crossed (the same fail from the same IP for the same user),
and only ONE when only one dimension crosses (credential stuffing across
many IPs, or one IP probing many usernames)."""

import blackwatch.correlation as correlation
from blackwatch.event import Actor, Event, Outcome, Source


def _fail(action="host.auth.ssh.failure", ip="1.2.3.4", user="root"):
    return Event(
        source=Source(module="ec2.host"),
        action=action,
        outcome=Outcome.failure,
        actor=Actor(principal=user, source_ip=ip),
    )


def setup_function(_fn):
    correlation.reset_state()


# ---------- baseline behavior ----------

def test_below_threshold_emits_nothing(monkeypatch):
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    for _ in range(correlation.THRESHOLD - 1):
        assert correlation.observe(_fail()) == []


def test_at_threshold_emits_both_dimensions(monkeypatch):
    """Same IP, same user: both per-IP and per-user thresholds cross on the
    same event, so we emit both signals."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out = []
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail()))
    actions = {e.action for e in out}
    assert actions == {"host.bruteforce", "host.bruteforce.user"}

    ip_ev = next(e for e in out if e.action == "host.bruteforce")
    user_ev = next(e for e in out if e.action == "host.bruteforce.user")
    assert ip_ev.actor.source_ip == "1.2.3.4"
    assert ip_ev.extra["dimension"] == "source_ip"
    assert ip_ev.extra["count_in_window"] == correlation.THRESHOLD
    assert ip_ev.extra["threshold"] == correlation.THRESHOLD
    assert user_ev.actor.principal == "root"
    assert user_ev.extra["dimension"] == "principal"


def test_repeats_within_window_are_suppressed(monkeypatch):
    """Each dimension suppresses independently — emits once per window."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for _ in range(10):  # double the threshold
        out.extend(correlation.observe(_fail()))
    actions = sorted(e.action for e in out)
    # exactly one of each — no flood
    assert actions == ["host.bruteforce", "host.bruteforce.user"]


def test_window_expiry_allows_re_emit(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(correlation, "_now", lambda: t["now"])
    for _ in range(correlation.THRESHOLD):
        correlation.observe(_fail())   # first burst -> 2 alerts (one per dim)
    # advance past the suppression window AND clear the window history
    t["now"] = 1000.0 + correlation.WINDOW_SECONDS + 1
    out: list = []
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail()))
    # second burst can fire again on both dims
    assert sorted(e.action for e in out) == ["host.bruteforce", "host.bruteforce.user"]


def test_no_source_ip_still_counts_user(monkeypatch):
    """If the event has no source IP, the per-IP detector skips it but the
    per-user detector should still accumulate. This protects against
    log shapes that drop IPs (PAM-only failures, etc.)."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for _ in range(correlation.THRESHOLD):
        ev = _fail(ip=None)
        ev.actor.source_ip = None
        out.extend(correlation.observe(ev))
    actions = {e.action for e in out}
    assert actions == {"host.bruteforce.user"}  # only the user dim, no IP dim


def test_no_principal_still_counts_ip(monkeypatch):
    """Mirror of above — anonymous-but-IP-bearing failures still trip the
    per-IP detector even when we can't attribute to a user."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(user=None)))
    actions = {e.action for e in out}
    assert actions == {"host.bruteforce"}


def test_unrelated_actions_ignored(monkeypatch):
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    for _ in range(20):
        assert correlation.observe(_fail(action="host.auth.ssh.success")) == []


def test_vpn_failure_also_watched(monkeypatch):
    """VPN auth-failure events trigger both VPN-flavored derived actions."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(action="vpn.auth.failure")))
    actions = sorted(e.action for e in out)
    assert actions == ["vpn.bruteforce", "vpn.bruteforce.user"]
    # All emitted events route through the vpn.openvpn module so the existing
    # vpn rule pipeline picks them up.
    assert {e.source.module for e in out} == {"vpn.openvpn"}


# ---------- per-IP dimension isolation (existing behavior, refined) ----------

def test_per_ip_isolation_fires_each_ip_then_user_suppressed(monkeypatch):
    """Same user attacked from two different IPs in sequence:
       - Burst 1 (5 fails from IP-A as root): IP-A fires + root fires.
       - Burst 2 (5 fails from IP-B as root): IP-B fires; root already
         alerted in this window so it's suppressed.
       Total: 3 events (2 IP-flavored + 1 user-flavored)."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(ip="1.1.1.1")))
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(ip="2.2.2.2")))
    ips_fired = sorted(e.actor.source_ip for e in out if e.action == "host.bruteforce")
    users_fired = [e.actor.principal for e in out if e.action == "host.bruteforce.user"]
    assert ips_fired == ["1.1.1.1", "2.2.2.2"]
    assert users_fired == ["root"]  # only once — user-dim suppression held


# ---------- per-user dimension (NEW signal — catches credential stuffing) ----

def test_credential_stuffing_across_ips_fires_user_dim_only(monkeypatch):
    """5 fails for the same user from 5 different IPs (1 fail per IP):
    per-IP dim never crosses threshold (each IP only has 1 fail), per-user
    dim does. Before this addition the attack would have gone undetected."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for i in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(ip=f"10.0.0.{i + 1}", user="alice")))
    actions = {e.action for e in out}
    assert actions == {"host.bruteforce.user"}
    user_ev = out[0]
    assert user_ev.actor.principal == "alice"
    assert user_ev.extra["dimension"] == "principal"
    assert user_ev.extra["count_in_window"] == correlation.THRESHOLD


def test_per_user_isolation(monkeypatch):
    """5 fails for 'alice' from one IP, then 5 fails for 'bob' from the same IP:
       - First burst: IP fires, 'alice' fires.
       - Second burst: IP suppressed (already fired this window), 'bob' fires.
       Total: 1 IP + 2 users = 3 events."""
    monkeypatch.setattr(correlation, "_now", lambda: 1000.0)
    out: list = []
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(ip="9.9.9.9", user="alice")))
    for _ in range(correlation.THRESHOLD):
        out.extend(correlation.observe(_fail(ip="9.9.9.9", user="bob")))
    ip_actions = [e for e in out if e.action == "host.bruteforce"]
    user_actions = [e for e in out if e.action == "host.bruteforce.user"]
    assert len(ip_actions) == 1
    assert {e.actor.principal for e in user_actions} == {"alice", "bob"}
