from __future__ import annotations

import ipaddress
import os
import tempfile

import pytest


@pytest.fixture()
def isolated_intel_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="bw-intel-")
    monkeypatch.setenv("BLACKWATCH_DATA_DIR", tmp)
    # Force reload so cached module-level state (paths) is fresh.
    from blackwatch.intel import db, enrich

    db.init()
    enrich._cache.clear()
    yield db


def _range_of(cidr: str) -> tuple[int, int]:
    net = ipaddress.ip_network(cidr, strict=False)
    return int(net.network_address), int(net.broadcast_address)


def test_enrich_matches_spamhaus_feed(isolated_intel_db):
    from blackwatch.event import (
        Actor,
        Event,
        Observable,
        ObservableType,
        Source,
        Transport,
    )
    from blackwatch.intel import db, enrich

    # Use a real public range — TEST-NET (203.0.113/24) is is_reserved and
    # would short-circuit to the bogon path before feed lookup.
    bad_cidr = "8.8.8.0/24"
    bad_ip = "8.8.8.42"
    s, e = _range_of(bad_cidr)
    db.replace_feed("spamhaus_drop", "test://", [(s, e, "spamhaus,drop")])

    ev = Event(
        source=Source(module="test", transport=Transport.webhook),
        action="test.event",
        observables=[Observable(type=ObservableType.ip, value=bad_ip)],
        actor=Actor(),
    )
    enrich.enrich_event(ev)
    assert "intel" in ev.extra
    assert "spamhaus_drop" in ev.extra["intel"]["feeds"]
    assert ev.extra["intel"]["is_bogon"] is False


def test_enrich_marks_bogon(isolated_intel_db):
    from blackwatch.event import (
        Event,
        Observable,
        ObservableType,
        Source,
        Transport,
    )
    from blackwatch.intel import enrich

    ev = Event(
        source=Source(module="test", transport=Transport.webhook),
        observables=[Observable(type=ObservableType.ip, value="10.0.0.5")],
    )
    enrich.enrich_event(ev)
    assert ev.extra["intel"]["is_bogon"] is True
    assert ev.extra["intel"]["feeds"] == []
