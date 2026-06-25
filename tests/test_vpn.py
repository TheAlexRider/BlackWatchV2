"""OpenVPN module tests: status parsing (v1 + v3), adapter, projection diffs.
No DB required — the pure projection helpers are tested directly."""

from datetime import datetime, timezone

import json

from blackwatch.modules.base import IngestContext
from blackwatch.modules.vpn_openvpn import VpnOpenVpnAdapter, parse_auth_lines, parse_status
from blackwatch.vpn.projection import detect_concurrent, diff_sessions

NOW = datetime(2026, 5, 25, tzinfo=timezone.utc)

STATUS_V1 = """OpenVPN CLIENT LIST
Updated,Thu Jun 18 08:12:15 2015
Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
alice,1.2.3.4:50001,1000,2000,Thu Jun 18 08:00:00 2015
bob,5.6.7.8:51000,500,800,Thu Jun 18 08:05:00 2015
ROUTING TABLE
Virtual Address,Common Name,Real Address,Last Ref
10.8.0.2,alice,1.2.3.4:50001,Thu Jun 18 08:10:00 2015
10.8.0.3,bob,5.6.7.8:51000,Thu Jun 18 08:11:00 2015
GLOBAL STATS
Max bcast/mcast queue length,0
END
"""

_V3_ROWS = [
    "\t".join(["HEADER", "CLIENT_LIST", "Common Name", "Real Address", "Virtual Address"]),
    "\t".join(["CLIENT_LIST", "alice", "1.2.3.4:50001", "10.8.0.2", "", "1000", "2000",
               "Thu Jun 18 08:00:00 2015", "1434614400", "alice-user", "1", "0", "AES-128-GCM"]),
    "\t".join(["CLIENT_LIST", "bob", "5.6.7.8:51000", "10.8.0.3", "", "500", "800",
               "Thu Jun 18 08:05:00 2015", "1434614700", "bob-user", "2", "1", "AES-128-GCM"]),
]
STATUS_V3 = "\n".join(_V3_ROWS) + "\n"


def test_parse_v1():
    clients = parse_status(STATUS_V1)
    assert len(clients) == 2
    alice = next(c for c in clients if c["common_name"] == "alice")
    assert alice["real_ip"] == "1.2.3.4"
    assert alice["real_address"] == "1.2.3.4:50001"
    assert alice["virtual_address"] == "10.8.0.2"  # mapped from routing table
    assert alice["username"] is None  # v1 has no username field


def test_parse_v3_has_username():
    clients = parse_status(STATUS_V3)
    assert len(clients) == 2
    alice = next(c for c in clients if c["common_name"] == "alice")
    assert alice["username"] == "alice-user"
    assert alice["real_ip"] == "1.2.3.4"
    assert alice["virtual_address"] == "10.8.0.2"


def test_parse_empty():
    assert parse_status("") == []


def test_adapter_emits_health_and_snapshot():
    adapter = VpnOpenVpnAdapter()
    ctx = IngestContext(module="vpn.openvpn", transport="poll")
    events = adapter.parse(
        {"kind": "poll", "server": "vpn-1", "state": "active", "active": True,
         "status_raw": STATUS_V1},
        ctx,
    )
    actions = [e.action for e in events]
    assert "vpn.service.health" in actions
    assert "vpn.status.snapshot" in actions

    health = next(e for e in events if e.action == "vpn.service.health")
    assert health.outcome.value == "success"
    assert health.target.id == "vpn-1"

    snap = next(e for e in events if e.action == "vpn.status.snapshot")
    assert snap.extra["client_count"] == 2
    ips = {o.value for o in snap.observables if o.type.value == "ip"}
    assert ips == {"1.2.3.4", "5.6.7.8"}


def test_adapter_service_down():
    adapter = VpnOpenVpnAdapter()
    ctx = IngestContext(module="vpn.openvpn", transport="poll")
    events = adapter.parse({"server": "vpn-1", "state": "failed", "active": False}, ctx)
    health = next(e for e in events if e.action == "vpn.service.health")
    assert health.outcome.value == "failure"


def test_diff_sessions_detects_join_and_leave():
    prev = parse_status(STATUS_V1)  # alice + bob
    current = [c for c in prev if c["common_name"] == "alice"]  # bob left
    new_client = {"common_name": "carol", "real_address": "9.9.9.9:5", "real_ip": "9.9.9.9"}
    current.append(new_client)  # carol joined

    events = diff_sessions("vpn-1", prev, current, NOW)
    starts = [e for e in events if e.action == "vpn.session.start"]
    ends = [e for e in events if e.action == "vpn.session.end"]
    assert [e.actor.principal for e in starts] == ["carol"]
    assert [e.actor.principal for e in ends] == ["bob"]


_FAIL_LINE = json.dumps({
    "__CURSOR": "c-fail-1",
    "__REALTIME_TIMESTAMP": "1779766537000000",
    "MESSAGE": "223.184.96.9:63403 SENT CONTROL [apoorvasharma]: 'AUTH_FAILED'",
})
_OK_LINE = json.dumps({
    "__CURSOR": "c-ok-1",
    "__REALTIME_TIMESTAMP": "1779766540000000",
    "MESSAGE": "73.9.38.62:37970 TLS: Username/Password authentication succeeded for username 'sanket.patil'",
})


def test_parse_auth_lines_failure_and_success():
    events = parse_auth_lines([_FAIL_LINE, _OK_LINE], "vpn-1")
    assert len(events) == 2

    fail = next(e for e in events if e.action == "vpn.auth.failure")
    assert fail.outcome.value == "failure"
    assert fail.actor.principal == "apoorvasharma"
    assert fail.actor.source_ip == "223.184.96.9"

    ok = next(e for e in events if e.action == "vpn.auth.success")
    assert ok.outcome.value == "success"
    assert ok.actor.principal == "sanket.patil"
    assert ok.actor.source_ip == "73.9.38.62"


def test_parse_auth_lines_event_id_is_deterministic():
    # Re-reading the same journal line (overlapping windows) must not duplicate.
    first = parse_auth_lines([_FAIL_LINE], "vpn-1")[0]
    second = parse_auth_lines([_FAIL_LINE], "vpn-1")[0]
    assert first.event_id == second.event_id


def test_parse_auth_lines_ignores_noise():
    noise = json.dumps({"__CURSOR": "x", "MESSAGE": "TLS: Initial packet from ..."})
    assert parse_auth_lines([noise, "not-json"], "vpn-1") == []


def test_adapter_emits_auth_events_from_poll():
    adapter = VpnOpenVpnAdapter()
    ctx = IngestContext(module="vpn.openvpn", transport="poll")
    events = adapter.parse(
        {"kind": "poll", "server": "vpn-1", "state": "active", "active": True,
         "status_raw": None, "auth_lines": [_FAIL_LINE, _OK_LINE]},
        ctx,
    )
    actions = [e.action for e in events]
    assert "vpn.auth.failure" in actions
    assert "vpn.auth.success" in actions


def test_adapter_accepts_vpn_report_from_push_agent():
    """vpn_agent.py ships kind="vpn_report" with host metadata; the adapter
    must stamp agent_version / instance_id / uptime onto the heartbeat extras
    so the per-host detail page can show "reporting" / "stale" the same way it
    does for the EC2 agent."""
    adapter = VpnOpenVpnAdapter()
    ctx = IngestContext(module="vpn.openvpn", transport="queue",
                        account="111122223333", region="us-west-1")
    payload = {
        "kind": "vpn_report",
        "server": "openvpn",
        "agent_version": "0.1",
        "uptime_seconds": 4242,
        "host": {"instance_id": "i-abc123", "hostname": "vpn-prod-1",
                 "account": "111122223333", "region": "us-west-1"},
        "state": "active",
        "active": True,
        "status_raw": STATUS_V1,
        "auth_lines": [_FAIL_LINE],
    }
    events = adapter.parse(payload, ctx)

    health = next(e for e in events if e.action == "vpn.service.health")
    assert health.outcome.value == "success"
    assert health.source.transport.value == "queue"     # honored ctx.transport
    assert health.source.account == "111122223333"      # promoted from host{}
    assert health.source.region == "us-west-1"
    assert health.extra["agent_version"] == "0.1"
    assert health.extra["uptime_seconds"] == 4242
    assert health.extra["instance_id"] == "i-abc123"
    assert health.extra["hostname"] == "vpn-prod-1"

    # The snapshot + auth events still come out alongside.
    assert any(e.action == "vpn.status.snapshot" for e in events)
    assert any(e.action == "vpn.auth.failure" for e in events)


def test_adapter_accepts_realtime_burst_from_follower():
    """vpn_agent.py's follower thread ships kind="vpn_auth_realtime" with
    only `auth_lines` populated — no state/active, no status_raw. The adapter
    must emit JUST the auth events, with no spurious health/snapshot."""
    adapter = VpnOpenVpnAdapter()
    ctx = IngestContext(module="vpn.openvpn", transport="queue")
    payload = {
        "kind": "vpn_auth_realtime",
        "server": "openvpn",
        "agent_version": "0.2",
        "host": {"instance_id": "i-abc123"},
        "auth_lines": [_FAIL_LINE, _OK_LINE],
    }
    events = adapter.parse(payload, ctx)
    actions = [e.action for e in events]
    assert "vpn.auth.failure" in actions
    assert "vpn.auth.success" in actions
    # No service.health (no state/active) and no status.snapshot (no status_raw).
    assert "vpn.service.health" not in actions
    assert "vpn.status.snapshot" not in actions


def test_adapter_unknown_transport_falls_back_to_poll():
    """A malformed ctx.transport must not crash the adapter — fall back to
    poll so events still flow."""
    adapter = VpnOpenVpnAdapter()
    ctx = IngestContext(module="vpn.openvpn", transport="garbage")
    events = adapter.parse({"server": "vpn-1", "state": "active", "active": True}, ctx)
    health = next(e for e in events if e.action == "vpn.service.health")
    assert health.source.transport.value == "poll"


def test_detect_concurrent():
    clients = [
        {"common_name": "alice", "username": "alice", "real_address": "1.1.1.1:1", "real_ip": "1.1.1.1"},
        {"common_name": "alice", "username": "alice", "real_address": "2.2.2.2:1", "real_ip": "2.2.2.2"},
        {"common_name": "bob", "username": "bob", "real_address": "3.3.3.3:1", "real_ip": "3.3.3.3"},
    ]
    events = detect_concurrent("vpn-1", clients, NOW)
    assert len(events) == 1
    assert events[0].action == "vpn.session.concurrent"
    assert events[0].actor.principal == "alice"
    assert set(events[0].extra["source_ips"]) == {"1.1.1.1", "2.2.2.2"}
