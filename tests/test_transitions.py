"""Transition-only storage: routine heartbeats/snapshots feed projections but
don't get stored; the projections emit transition events on real state change."""

from blackwatch.hosts.projection import _host_transition
from blackwatch.pipeline import _PROJECTION_ONLY_ACTIONS
from blackwatch.vpn.projection import _service_transition


def test_projection_only_set_covers_routine_telemetry():
    # These are the "still alive / still the same" events we drop at storage
    # time — they drive projections but never get stored or notified directly.
    # Any additions to this set should be intentional.
    assert _PROJECTION_ONLY_ACTIONS == {
        "vpn.service.health",
        "vpn.status.snapshot",
        "host.service.health",
        "host.state.snapshot",
        "probe.agent.heartbeat",
        "service.probe.result",
        "s3.bucket.snapshot",
        "s3.scan.completed",
        "aws.posture.finding",
        "aws.posture.scan.completed",
    }


# ---- VPN service transitions -------------------------------------------------

def test_vpn_no_prior_and_active_first_seen():
    assert _service_transition(prev_active=None, new_active=True) == "vpn.service.up"


def test_vpn_up_to_down():
    assert _service_transition(prev_active=True, new_active=False) == "vpn.service.down"


def test_vpn_down_to_up_recovered():
    assert _service_transition(prev_active=False, new_active=True) == "vpn.service.up"


def test_vpn_still_up_no_transition():
    assert _service_transition(prev_active=True, new_active=True) is None


def test_vpn_still_down_no_transition():
    assert _service_transition(prev_active=False, new_active=False) is None


# ---- Host transitions --------------------------------------------------------

def test_host_first_seen():
    assert _host_transition(prev_active=None) == "host.first_seen"


def test_host_recovered_from_stale():
    assert _host_transition(prev_active=False) == "host.agent.recovered"


def test_host_still_active_no_transition():
    assert _host_transition(prev_active=True) is None
