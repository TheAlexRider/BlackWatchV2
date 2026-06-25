"""EC2 host adapter + generalized SQS connector tests. No AWS/network."""

import json

from blackwatch.connectors.models import AwsCloudtrailSqsConfig
from blackwatch.modules.base import IngestContext
from blackwatch.modules.ec2_host import Ec2HostAdapter


def _journal(msg, cursor="c1", ts="1779766537000000"):
    return json.dumps({"__CURSOR": cursor, "__REALTIME_TIMESTAMP": ts, "MESSAGE": msg})


def _report(auth_msgs):
    return {
        "kind": "ec2_report",
        "host": {"instance_id": "i-0abc", "hostname": "ip-172-16-1-97",
                 "account": "095899260107", "region": "us-west-1"},
        "agent_version": "0.1",
        "uptime_seconds": 4242,
        "auth_events": [_journal(m, cursor=f"c{i}") for i, m in enumerate(auth_msgs)],
    }


def _ctx():
    return IngestContext(module="ec2.host", transport="queue")


def test_heartbeat_event():
    events = Ec2HostAdapter().parse(_report([]), _ctx())
    hb = next(e for e in events if e.action == "host.service.health")
    assert hb.outcome.value == "success"
    assert hb.target.id == "i-0abc"
    assert hb.source.account == "095899260107"
    assert hb.extra["uptime_seconds"] == 4242


def test_ssh_success_and_failure():
    events = Ec2HostAdapter().parse(
        _report([
            "Accepted publickey for ec2-user from 1.2.3.4 port 5 ssh2: RSA SHA256:abc",
            "Failed password for invalid user admin from 9.9.9.9 port 6 ssh2",
        ]),
        _ctx(),
    )
    ok = next(e for e in events if e.action == "host.auth.ssh.success")
    assert ok.actor.principal == "ec2-user" and ok.actor.source_ip == "1.2.3.4"
    bad = next(e for e in events if e.action == "host.auth.ssh.failure")
    assert bad.actor.principal == "admin" and bad.actor.source_ip == "9.9.9.9"
    assert bad.outcome.value == "failure"


def test_sudo_exec_and_failure():
    events = Ec2HostAdapter().parse(
        _report([
            "sudo:   ec2-user : TTY=pts/0 ; PWD=/home/ec2-user ; USER=root ; COMMAND=/bin/cat /etc/shadow",
            "sudo:   baduser : 1 incorrect password attempt ; TTY=pts/1 ; USER=root",
        ]),
        _ctx(),
    )
    ex = next(e for e in events if e.action == "host.sudo.exec")
    assert ex.actor.principal == "ec2-user"
    assert "cat /etc/shadow" in ex.extra["command"]
    fail = next(e for e in events if e.action == "host.sudo.failure")
    assert fail.actor.principal == "baduser"


def test_deterministic_auth_id():
    r = _report(["Failed password for ec2-user from 9.9.9.9 port 6 ssh2"])
    a = next(e for e in Ec2HostAdapter().parse(r, _ctx()) if e.action == "host.auth.ssh.failure")
    b = next(e for e in Ec2HostAdapter().parse(r, _ctx()) if e.action == "host.auth.ssh.failure")
    assert a.event_id == b.event_id  # same cursor -> dedup on insert


def test_non_report_ignored():
    assert Ec2HostAdapter().parse({"kind": "something_else"}, _ctx()) == []


# -------- Phase B: snapshots + diff -----------------------------------------

from blackwatch.hosts.diff import diff_snapshots


def test_adapter_emits_snapshot_event_when_present():
    rpt = _report([])
    rpt["snapshots"] = {
        "ports": [{"proto": "tcp", "address": "0.0.0.0", "port": "22"}],
        "users": [], "authorized_keys": [], "sudoers": {},
    }
    events = Ec2HostAdapter().parse(rpt, _ctx())
    snap = next(e for e in events if e.action == "host.state.snapshot")
    assert snap.extra["snapshots"]["ports"][0]["port"] == "22"


def test_adapter_omits_snapshot_event_when_absent():
    events = Ec2HostAdapter().parse(_report([]), _ctx())  # no snapshots key
    assert not any(e.action == "host.state.snapshot" for e in events)


def test_diff_no_change_emits_nothing():
    snap = {"ports": [], "users": [], "authorized_keys": [], "sudoers": {}}
    assert diff_snapshots(snap, snap) == []


def test_diff_new_port_and_user_and_key():
    prev = {
        "ports": [{"proto": "tcp", "address": "0.0.0.0", "port": "22"}],
        "users": [{"name": "ec2-user"}],
        "authorized_keys": [{"user": "ec2-user", "fingerprint": "abc"}],
        "sudoers": {"/etc/sudoers": "h1"},
    }
    cur = {
        "ports": [
            {"proto": "tcp", "address": "0.0.0.0", "port": "22"},
            {"proto": "tcp", "address": "0.0.0.0", "port": "8080", "process": "users:((\"node\"))"},
        ],
        "users": [{"name": "ec2-user"}, {"name": "evil", "uid": "1100", "shell": "/bin/bash"}],
        "authorized_keys": [
            {"user": "ec2-user", "fingerprint": "abc"},
            {"user": "ec2-user", "fingerprint": "xyz", "preview": "ssh-rsa AAAA…"},
        ],
        "sudoers": {"/etc/sudoers": "h2"},  # changed
    }
    out = dict((a, e) for a, e in diff_snapshots(prev, cur))
    assert "host.port.opened" in out and out["host.port.opened"]["port"] == "8080"
    assert "host.user.added" in out and out["host.user.added"]["user"] == "evil"
    assert "host.authorized_key.added" in out and out["host.authorized_key.added"]["fingerprint"] == "xyz"
    assert "host.sudoers.changed" in out
    assert out["host.sudoers.changed"]["changes"]["/etc/sudoers"] == "changed"


def test_diff_removed_port_and_key():
    prev = {
        "ports": [{"proto": "tcp", "address": "0.0.0.0", "port": "8080"}],
        "authorized_keys": [{"user": "ec2-user", "fingerprint": "abc"}],
    }
    cur = {"ports": [], "authorized_keys": []}
    out = [a for a, _ in diff_snapshots(prev, cur)]
    assert "host.port.closed" in out
    assert "host.authorized_key.removed" in out


# -------- Phase C: FIM + persistence + packages -----------------------------

def test_diff_critical_files_and_cron():
    prev = {
        "critical_files": {"/etc/passwd": "h1", "/etc/ssh/sshd_config": "h2"},
        "cron": {"/etc/crontab": "c1"},
    }
    cur = {
        "critical_files": {"/etc/passwd": "h1NEW", "/etc/ssh/sshd_config": "h2"},  # changed
        "cron": {"/etc/crontab": "c1", "/etc/cron.d/evil": "cX"},                  # added
    }
    out = list(diff_snapshots(prev, cur))
    file_events = [e for e in out if e[0] == "host.file.changed"]
    cron_events = [e for e in out if e[0] == "host.cron.changed"]
    assert any(e[1]["path"] == "/etc/passwd" and e[1]["change"] == "changed" for e in file_events)
    assert any(e[1]["path"] == "/etc/cron.d/evil" and e[1]["change"] == "added" for e in cron_events)


def test_diff_systemd_units_and_suid():
    prev = {"systemd_units": ["sshd.service"], "suid": ["/usr/bin/sudo"]}
    cur = {
        "systemd_units": ["sshd.service", "evil.service"],
        "suid": ["/usr/bin/sudo", "/tmp/pwn"],
    }
    out = dict(diff_snapshots(prev, cur))
    assert out["host.service.added"]["unit"] == "evil.service"
    assert out["host.suid.added"]["path"] == "/tmp/pwn"


def test_diff_packages_summary():
    prev = {"packages": ["openssh", "vim"]}
    cur = {"packages": ["openssh", "nmap", "netcat"]}  # vim removed; nmap+netcat added
    out = dict(diff_snapshots(prev, cur))
    pkg = out["host.packages.changed"]
    assert set(pkg["added"]) == {"nmap", "netcat"}
    assert pkg["removed"] == ["vim"]
    assert pkg["added_count"] == 2 and pkg["removed_count"] == 1


def test_diff_skips_new_category_baseline():
    # Phase B -> Phase C scenario: previous snapshot didn't have suid/packages.
    # The new categories must NOT flood as "all added" — they baseline silently.
    prev = {"ports": [{"proto": "tcp", "address": "0.0.0.0", "port": "22"}]}
    cur = {
        "ports": [{"proto": "tcp", "address": "0.0.0.0", "port": "22"}],   # unchanged
        "suid": ["/usr/bin/sudo", "/usr/bin/passwd"],                       # new category
        "packages": ["openssh", "vim"],                                     # new category
    }
    out = list(diff_snapshots(prev, cur))
    assert out == []  # no events at all


def test_diff_skips_failed_collector_on_current():
    # A transient collector failure on `current` (key omitted) must NOT emit
    # "everything removed" events.
    prev = {"suid": ["/usr/bin/sudo", "/usr/bin/passwd"]}
    cur = {}  # suid collection failed this cycle -> key omitted
    assert diff_snapshots(prev, cur) == []


def test_sqs_connector_target_module():
    default = AwsCloudtrailSqsConfig(queue_url="https://q")
    assert default.target_module == "aws.cloudtrail"  # back-compat for existing rows
    ec2 = AwsCloudtrailSqsConfig(queue_url="https://q", target_module="ec2.host")
    assert ec2.target_module == "ec2.host"


# -------- v1.0 production additions -----------------------------------------

def test_adapter_promotes_tags_onto_every_event():
    """BLACKWATCH_TAGS lets the operator say `env=prod`; the adapter must
    promote these onto every emitted event so rules can match on
    `extra.tags.env equals prod`. Without this, per-env routing can't work."""
    rpt = _report(["Failed password for ec2-user from 1.2.3.4 port 5 ssh2"])
    rpt["host"]["tags"] = {"env": "prod", "role": "api"}
    rpt["snapshots"] = {"ports": []}
    events = Ec2HostAdapter().parse(rpt, _ctx())
    # All emitted events carry the tag dict so rule matching works uniformly.
    for e in events:
        assert e.extra.get("tags") == {"env": "prod", "role": "api"}, \
            f"{e.action} missing tags"


def test_adapter_surfaces_tick_duration_and_collector_errors():
    rpt = _report([])
    rpt["tick_duration_ms"] = 87
    rpt["collector_errors"] = {"packages": "rpm exit=1"}
    events = Ec2HostAdapter().parse(rpt, _ctx())
    hb = next(e for e in events if e.action == "host.service.health")
    assert hb.extra["tick_duration_ms"] == 87
    assert hb.extra["collector_errors"] == {"packages": "rpm exit=1"}


def test_diff_kernel_modules_added_and_removed():
    prev = {"kernel_modules": ["xfs", "ext4"]}
    cur = {"kernel_modules": ["xfs", "ext4", "evil_lkm"]}
    out = list(diff_snapshots(prev, cur))
    assert ("host.kernel.module.added", {"module": "evil_lkm"}) in out


def test_diff_disk_crosses_warn_threshold():
    """Stable below 90 -> spike to 92 fires one host.disk.warn for that mount."""
    prev = {"disk": [{"mount": "/", "fs_type": "ext4", "total": 100, "used": 50, "used_pct": 50}]}
    cur = {"disk": [{"mount": "/", "fs_type": "ext4", "total": 100, "used": 92, "used_pct": 92}]}
    out = dict(diff_snapshots(prev, cur))
    assert "host.disk.warn" in out
    assert out["host.disk.warn"]["mount"] == "/"
    assert out["host.disk.warn"]["used_pct"] == 92


def test_diff_disk_crosses_critical_threshold():
    prev = {"disk": [{"mount": "/var", "fs_type": "xfs", "total": 100, "used": 80, "used_pct": 80}]}
    cur = {"disk": [{"mount": "/var", "fs_type": "xfs", "total": 100, "used": 97, "used_pct": 97}]}
    out = dict(diff_snapshots(prev, cur))
    assert "host.disk.critical" in out


def test_diff_disk_hysteresis_band_doesnt_flap():
    """Hover at 87% (between recover=85 and warn=90) must not emit warn or
    recovered repeatedly — the band absorbs noise."""
    prev = {"disk": [{"mount": "/", "fs_type": "ext4", "total": 100, "used": 70, "used_pct": 70}]}
    cur = {"disk": [{"mount": "/", "fs_type": "ext4", "total": 100, "used": 87, "used_pct": 87}]}
    out = list(diff_snapshots(prev, cur))
    # Nothing emitted — 87 sits in the hysteresis band, neither warn nor recovered.
    assert not any(a.startswith("host.disk.") for a, _ in out)


def test_diff_disk_recovered_below_85():
    prev = {"disk": [{"mount": "/", "fs_type": "ext4", "total": 100, "used": 96, "used_pct": 96}]}
    cur = {"disk": [{"mount": "/", "fs_type": "ext4", "total": 100, "used": 70, "used_pct": 70}]}
    out = dict(diff_snapshots(prev, cur))
    assert "host.disk.recovered" in out


# -------- v1.1 agent: memory, CPU baseline, OOM, rpm DB, collector stall ----

from blackwatch.hosts.projection import (
    _baseline_stdev,
    _compute_state_transitions,
    _is_cpu_anomalous,
    _update_cpu_baseline,
)


def test_adapter_passes_v11_fields_through():
    """memory/cpu/active_sessions/rpm_db_corrupted/stalled_collectors land on
    the heartbeat event so the projection can act on them."""
    rpt = _report([])
    rpt["memory"] = {"total_kb": 1000000, "available_kb": 100000,
                    "used_kb": 900000, "used_pct": 90}
    rpt["cpu"] = {"load_1min": 0.5, "load_5min": 0.4, "load_15min": 0.3,
                  "cpu_count": 2, "load_norm_1min": 0.25, "load_norm_5min": 0.2}
    rpt["active_sessions"] = [{"user": "ec2-user", "tty": "pts/0",
                                "login": "Jun 5 12:00", "source": "10.0.0.5"}]
    rpt["rpm_db_corrupted"] = None
    rpt["stalled_collectors"] = []
    events = Ec2HostAdapter().parse(rpt, _ctx())
    hb = next(e for e in events if e.action == "host.service.health")
    assert hb.extra["memory"]["used_pct"] == 90
    assert hb.extra["cpu"]["load_norm_1min"] == 0.25
    assert hb.extra["active_sessions"][0]["user"] == "ec2-user"
    assert hb.extra["stalled_collectors"] == []


def test_adapter_emits_oom_kill_per_event_with_deterministic_id():
    rpt = _report([])
    rpt["oom_events"] = [
        {"cursor": "c-oom-1", "ts": "1780000000000000",
         "message": "Out of memory: Killed process 1234 (evil)"},
    ]
    events_a = Ec2HostAdapter().parse(rpt, _ctx())
    events_b = Ec2HostAdapter().parse(rpt, _ctx())
    oom_a = next(e for e in events_a if e.action == "host.oom_kill")
    oom_b = next(e for e in events_b if e.action == "host.oom_kill")
    assert oom_a.event_id == oom_b.event_id  # cursor → uuid5 → dedup
    assert "Killed process" in oom_a.extra["kernel_message"]
    assert oom_a.outcome.value == "failure"


# ---------- Welford baseline ----------

def test_welford_baseline_updates_incrementally():
    state = None
    for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
        state = _update_cpu_baseline(state, {"load_norm_1min": v})
    assert state["n"] == 5
    # mean of [0.1..0.5] = 0.3
    assert abs(state["mean"] - 0.3) < 1e-9
    # stdev of [0.1..0.5] (sample) ≈ 0.158
    assert abs(_baseline_stdev(state) - 0.158113883) < 1e-6


def test_welford_skips_missing_cpu():
    """Heartbeats without a usable CPU sample must not corrupt the baseline."""
    state = _update_cpu_baseline({"n": 5, "mean": 0.3, "M2": 0.1}, {})
    assert state == {"n": 5, "mean": 0.3, "M2": 0.1}


# ---------- CPU anomaly detection ----------

def test_cpu_not_anomalous_when_baseline_too_small():
    """With <60 samples we don't have a baseline yet — never alert."""
    bl = {"n": 30, "mean": 0.1, "M2": 0.001}
    assert not _is_cpu_anomalous(bl, {"load_norm_1min": 5.0})


def test_cpu_not_anomalous_when_below_min_load():
    """A 'spike' from 0.001 to 0.05 might be 50x baseline but it's noise —
    real signal needs the load to be at least 0.5 normalized."""
    bl = {"n": 1000, "mean": 0.001, "M2": 1e-6}
    assert not _is_cpu_anomalous(bl, {"load_norm_1min": 0.05})


def test_cpu_anomalous_when_high_and_far_from_baseline():
    bl = {"n": 1000, "mean": 0.2, "M2": 0.01}  # stdev ≈ 0.0032
    # 0.9 is way more than 3 stdev above 0.2 AND meaningfully high
    assert _is_cpu_anomalous(bl, {"load_norm_1min": 0.9})


# ---------- State transitions ----------

def _hb_extra(**kwargs):
    base = {
        "memory": {"used_pct": 50, "available_kb": 500_000, "total_kb": 1_000_000},
        "cpu": {"load_norm_1min": 0.2, "load_1min": 0.4, "cpu_count": 2},
        "rpm_db_corrupted": None,
        "stalled_collectors": [],
    }
    base.update(kwargs)
    return base


def test_memory_exhausted_fires_only_on_transition():
    bl = {"n": 100, "mean": 0.2, "M2": 0.01}
    # 50% used: nothing.
    _, out = _compute_state_transitions(None, _hb_extra(), bl)
    assert not any(a == "host.memory.exhausted" for a, _ in out)
    # Jump to 96%: fire.
    prev = {"memory_exhausted": False, "cpu_anomaly_active": False,
            "consecutive_cpu_anomaly": 0, "consecutive_cpu_normal": 0,
            "rpm_db_corrupted_active": False, "stalled_collectors": []}
    _, out = _compute_state_transitions(prev,
                                          _hb_extra(memory={"used_pct": 96,
                                                              "available_kb": 40_000,
                                                              "total_kb": 1_000_000}),
                                          bl)
    assert any(a == "host.memory.exhausted" for a, _ in out)


def test_memory_recovered_after_falling_below_90():
    bl = {"n": 100, "mean": 0.2, "M2": 0.01}
    prev = {"memory_exhausted": True, "cpu_anomaly_active": False,
            "consecutive_cpu_anomaly": 0, "consecutive_cpu_normal": 0,
            "rpm_db_corrupted_active": False, "stalled_collectors": []}
    # At 91 we're in the hysteresis band — no transition.
    new_state, out = _compute_state_transitions(
        prev, _hb_extra(memory={"used_pct": 91, "available_kb": 90_000,
                                  "total_kb": 1_000_000}), bl)
    assert not any(a == "host.memory.recovered" for a, _ in out)
    assert new_state["memory_exhausted"] is True
    # At 80 we cross the recovery threshold.
    _, out = _compute_state_transitions(
        prev, _hb_extra(memory={"used_pct": 80, "available_kb": 200_000,
                                  "total_kb": 1_000_000}), bl)
    assert any(a == "host.memory.recovered" for a, _ in out)


def test_cpu_anomaly_requires_consecutive_samples():
    bl = {"n": 1000, "mean": 0.2, "M2": 0.001}  # stdev tight
    high_cpu = _hb_extra(cpu={"load_norm_1min": 1.5, "load_1min": 3.0, "cpu_count": 2})
    state = None
    last_out = []
    # 9 consecutive anomalous samples should NOT yet fire.
    for _ in range(9):
        state, last_out = _compute_state_transitions(state, high_cpu, bl)
    assert state["consecutive_cpu_anomaly"] == 9
    assert not any(a == "host.cpu.anomaly" for a, _ in last_out)
    # 10th sample fires.
    state, last_out = _compute_state_transitions(state, high_cpu, bl)
    assert any(a == "host.cpu.anomaly" for a, _ in last_out)
    assert state["cpu_anomaly_active"]


def test_cpu_anomaly_clears_after_5_normal_samples():
    bl = {"n": 1000, "mean": 0.2, "M2": 0.001}
    prev = {"memory_exhausted": False, "cpu_anomaly_active": True,
            "consecutive_cpu_anomaly": 10, "consecutive_cpu_normal": 0,
            "rpm_db_corrupted_active": False, "stalled_collectors": []}
    normal_cpu = _hb_extra(cpu={"load_norm_1min": 0.18, "load_1min": 0.36, "cpu_count": 2})
    state = prev
    last_out = []
    for _ in range(4):
        state, last_out = _compute_state_transitions(state, normal_cpu, bl)
    assert not any(a == "host.cpu.normal" for a, _ in last_out)
    state, last_out = _compute_state_transitions(state, normal_cpu, bl)
    assert any(a == "host.cpu.normal" for a, _ in last_out)
    assert not state["cpu_anomaly_active"]


def test_rpm_db_corruption_transitions():
    bl = {"n": 100, "mean": 0.2, "M2": 0.01}
    # First sight of corruption: emit corrupted.
    _, out = _compute_state_transitions(None,
        _hb_extra(rpm_db_corrupted={"lock_files": ["/var/lib/rpm/__db.001"], "lock_count": 1}), bl)
    assert any(a == "host.package_db.corrupted" for a, _ in out)
    # Stuck corrupted: no repeat events.
    prev = {"memory_exhausted": False, "cpu_anomaly_active": False,
            "consecutive_cpu_anomaly": 0, "consecutive_cpu_normal": 0,
            "rpm_db_corrupted_active": True, "stalled_collectors": []}
    _, out = _compute_state_transitions(prev,
        _hb_extra(rpm_db_corrupted={"lock_files": ["/var/lib/rpm/__db.001"], "lock_count": 1}), bl)
    assert not any(a == "host.package_db.corrupted" for a, _ in out)
    # Cleared (rpm_db_corrupted=None): emit recovered.
    _, out = _compute_state_transitions(prev, _hb_extra(rpm_db_corrupted=None), bl)
    assert any(a == "host.package_db.recovered" for a, _ in out)


def test_stalled_collectors_set_diff():
    bl = {"n": 100, "mean": 0.2, "M2": 0.01}
    # `packages` newly stalled.
    _, out = _compute_state_transitions(None,
        _hb_extra(stalled_collectors=["packages"]), bl)
    actions = [(a, e) for a, e in out]
    assert ("host.collector.stalled", {"collector": "packages"}) in actions
    # Still stalled — no repeat. + a new one (`suid`) appears.
    prev = {"memory_exhausted": False, "cpu_anomaly_active": False,
            "consecutive_cpu_anomaly": 0, "consecutive_cpu_normal": 0,
            "rpm_db_corrupted_active": False, "stalled_collectors": ["packages"]}
    _, out = _compute_state_transitions(prev,
        _hb_extra(stalled_collectors=["packages", "suid"]), bl)
    actions = [(a, e) for a, e in out]
    assert ("host.collector.stalled", {"collector": "suid"}) in actions
    assert ("host.collector.stalled", {"collector": "packages"}) not in actions
    # `packages` recovers; `suid` stays stalled.
    prev2 = {**prev, "stalled_collectors": ["packages", "suid"]}
    _, out = _compute_state_transitions(prev2,
        _hb_extra(stalled_collectors=["suid"]), bl)
    actions = [(a, e) for a, e in out]
    assert ("host.collector.recovered", {"collector": "packages"}) in actions
    assert not any(a == "host.collector.stalled" for a, _ in actions)
