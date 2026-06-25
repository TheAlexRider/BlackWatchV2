"""EC2 host state projection. Consumes host.* events and maintains the
host_status read-model.

Responsibilities per heartbeat:
  1. Update last-seen + active flag (existing).
  2. Memory transitions: 95% used -> host.memory.exhausted; <90% -> recovered (hysteresis).
  3. CPU anomaly transitions: maintain a per-host Welford running mean+variance
     over normalized load (load_1min / cpu_count). Once we have >=60 samples
     (one hour), declare anomaly when current > mean + 3·stdev AND load is
     meaningfully high (>=0.5). Require 10 consecutive anomalous samples to
     fire host.cpu.anomaly (so a single 10-second batch job doesn't page).
     Require 5 consecutive normal samples to clear -> host.cpu.normal.
  4. rpm-DB corruption transitions: corrupted (lock files + no rpm process) ->
     host.package_db.corrupted; cleared -> host.package_db.recovered.
  5. Collector stall transitions: per-collector set-diff -> host.collector.stalled
     and .recovered. Tells you within minutes when packages/SUID/etc. broke.

Snapshot handler (existing): processes host.state.snapshot, runs diff, emits
diff events + first-seen-process events.

Per-host projection state lives inside host_status.extra under underscore-
prefixed keys (_baseline_cpu, _state) so we can preserve it across heartbeats
without adding new columns or a migration. The agent never sends these keys."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Category, Event, Outcome, Source, Target, Transport
from .diff import diff_snapshots

_MODULE = "ec2.host"

# CPU anomaly tuning. All deliberately conservative — we want to never page on
# a Friday afternoon deploy, but always page on a cryptominer.
_BASELINE_MIN_SAMPLES = 60   # 1 hour of 1-min samples before any anomaly fires
_ANOMALY_SIGMAS = 3.0        # mean + 3·stdev = the upper bound of "normal"
_ANOMALY_MIN_LOAD = 0.5      # normalized load below this is never anomalous
_ANOMALY_CONSECUTIVE = 10    # samples above the bound before firing (10 min)
_NORMAL_CONSECUTIVE = 5      # samples below the bound before clearing (5 min)

# Memory thresholds + hysteresis band.
_MEM_EXHAUSTED_PCT = 95
_MEM_RECOVERED_PCT = 90


def project(event: Event) -> list[Event]:
    if event.source.module != _MODULE:
        return []
    instance_id = event.target.id or event.extra.get("instance_id")
    if not instance_id:
        return []

    if event.action == "host.service.health":
        return _project_heartbeat(event, instance_id)
    if event.action == "host.state.snapshot":
        return _project_snapshot(event, instance_id)
    return []


# ---------- Heartbeat: liveness + memory/CPU/db/stall transitions -----------

def _project_heartbeat(event: Event, instance_id: str) -> list[Event]:
    prev = storage.get_host_status(instance_id)
    prev_active = prev["active"] if prev else None
    prev_extra = (prev or {}).get("extra") or {}
    when = event.event_time or datetime.now(timezone.utc)
    e = event.extra

    # Update Welford baseline with this tick's CPU sample. The baseline persists
    # across upserts via merge into host_status.extra._baseline_cpu.
    new_baseline = _update_cpu_baseline(prev_extra.get("_baseline_cpu"), e.get("cpu"))

    # State transitions on memory / CPU-anomaly / rpm-DB / stalled-collectors.
    new_state, transitions = _compute_state_transitions(
        prev_extra.get("_state"), e, new_baseline,
    )

    # Persist the merged extra. Underscore-prefixed keys are projection-owned;
    # agent never sends them, so merging is safe.
    merged_extra = {
        **e,
        "_baseline_cpu": new_baseline,
        "_state": new_state,
    }
    storage.upsert_host_status(
        instance_id,
        hostname=e.get("hostname") or event.target.name,
        account=event.source.account,
        region=event.source.region,
        updated_at=when,
        active=True,
        extra=merged_extra,
    )

    derived: list[Event] = []
    liveness = _host_transition(prev_active)
    if liveness is not None:
        derived.append(_make_derived(event, instance_id, liveness,
                                      {"prev_active": prev_active}))
    for action, extra in transitions:
        derived.append(_make_derived(event, instance_id, action, extra))
    return derived


def _host_transition(prev_active) -> str | None:
    """Existing liveness transitions — unchanged."""
    if prev_active is None:
        return "host.first_seen"
    if prev_active is False:
        return "host.agent.recovered"
    return None


# ---------- Welford running mean+variance ----------------------------------

def _update_cpu_baseline(prev: dict | None, cpu: Any) -> dict:
    """Welford's online algorithm. M2 is the running sum of squared diffs from
    the mean — variance = M2 / (n-1). Stored as floats in host_status.extra."""
    state = dict(prev or {"n": 0, "mean": 0.0, "M2": 0.0})
    if not isinstance(cpu, dict):
        return state
    x = cpu.get("load_norm_1min")
    if not isinstance(x, (int, float)):
        return state
    n = int(state.get("n", 0)) + 1
    mean = float(state.get("mean", 0.0))
    M2 = float(state.get("M2", 0.0))
    delta = x - mean
    mean += delta / n
    delta2 = x - mean
    M2 += delta * delta2
    return {"n": n, "mean": mean, "M2": M2}


def _is_cpu_anomalous(baseline: dict, cpu: Any) -> bool:
    if not isinstance(baseline, dict) or not isinstance(cpu, dict):
        return False
    n = int(baseline.get("n", 0))
    if n < _BASELINE_MIN_SAMPLES:
        return False
    x = cpu.get("load_norm_1min")
    if not isinstance(x, (int, float)) or x < _ANOMALY_MIN_LOAD:
        return False
    mean = float(baseline.get("mean", 0.0))
    variance = float(baseline.get("M2", 0.0)) / max(1, n - 1)
    stdev = variance ** 0.5
    return x > (mean + _ANOMALY_SIGMAS * stdev)


def _baseline_stdev(baseline: dict | None) -> float:
    if not isinstance(baseline, dict):
        return 0.0
    n = int(baseline.get("n", 0))
    if n < 2:
        return 0.0
    return (float(baseline.get("M2", 0.0)) / (n - 1)) ** 0.5


# ---------- State transitions (memory / cpu / rpm-db / stalled) -------------

def _compute_state_transitions(
    prev_state: dict | None, event_extra: dict, new_baseline: dict,
) -> tuple[dict, list[tuple[str, dict[str, Any]]]]:
    prev_state = prev_state or {
        "memory_exhausted": False,
        "cpu_anomaly_active": False,
        "consecutive_cpu_anomaly": 0,
        "consecutive_cpu_normal": 0,
        "rpm_db_corrupted_active": False,
        "stalled_collectors": [],
    }
    new_state = dict(prev_state)
    out: list[tuple[str, dict[str, Any]]] = []

    # --- Memory ---
    mem = event_extra.get("memory") or {}
    used_pct = mem.get("used_pct")
    if isinstance(used_pct, (int, float)):
        if not prev_state.get("memory_exhausted") and used_pct >= _MEM_EXHAUSTED_PCT:
            new_state["memory_exhausted"] = True
            out.append(("host.memory.exhausted", {
                "used_pct": used_pct,
                "available_kb": mem.get("available_kb"),
                "total_kb": mem.get("total_kb"),
            }))
        elif prev_state.get("memory_exhausted") and used_pct < _MEM_RECOVERED_PCT:
            new_state["memory_exhausted"] = False
            out.append(("host.memory.recovered", {
                "used_pct": used_pct,
                "available_kb": mem.get("available_kb"),
            }))

    # --- CPU anomaly (baseline-relative, with hysteresis) ---
    cpu = event_extra.get("cpu") or {}
    if isinstance(cpu, dict) and cpu.get("load_norm_1min") is not None:
        is_anom = _is_cpu_anomalous(new_baseline, cpu)
        if is_anom:
            new_state["consecutive_cpu_anomaly"] = prev_state.get("consecutive_cpu_anomaly", 0) + 1
            new_state["consecutive_cpu_normal"] = 0
        else:
            new_state["consecutive_cpu_normal"] = prev_state.get("consecutive_cpu_normal", 0) + 1
            new_state["consecutive_cpu_anomaly"] = 0
        if (not prev_state.get("cpu_anomaly_active")
                and new_state["consecutive_cpu_anomaly"] >= _ANOMALY_CONSECUTIVE):
            new_state["cpu_anomaly_active"] = True
            out.append(("host.cpu.anomaly", {
                "load_norm_1min": cpu.get("load_norm_1min"),
                "load_1min": cpu.get("load_1min"),
                "cpu_count": cpu.get("cpu_count"),
                "baseline_mean": round(new_baseline.get("mean", 0.0), 3),
                "baseline_stdev": round(_baseline_stdev(new_baseline), 3),
                "baseline_n": new_baseline.get("n", 0),
            }))
        elif (prev_state.get("cpu_anomaly_active")
                and new_state["consecutive_cpu_normal"] >= _NORMAL_CONSECUTIVE):
            new_state["cpu_anomaly_active"] = False
            out.append(("host.cpu.normal", {
                "load_norm_1min": cpu.get("load_norm_1min"),
            }))

    # --- rpm DB corruption (BDB era — see vpn-info.md / docs) ---
    rpm_corrupted = event_extra.get("rpm_db_corrupted")
    if rpm_corrupted and not prev_state.get("rpm_db_corrupted_active"):
        new_state["rpm_db_corrupted_active"] = True
        out.append(("host.package_db.corrupted", {
            "lock_files": rpm_corrupted.get("lock_files", []),
            "lock_count": rpm_corrupted.get("lock_count", 0),
        }))
    elif (not rpm_corrupted) and prev_state.get("rpm_db_corrupted_active"):
        new_state["rpm_db_corrupted_active"] = False
        out.append(("host.package_db.recovered", {}))

    # --- Stalled collectors (set diff) ---
    stalled_now = set(event_extra.get("stalled_collectors") or [])
    stalled_prev = set(prev_state.get("stalled_collectors") or [])
    for name in sorted(stalled_now - stalled_prev):
        out.append(("host.collector.stalled", {"collector": name}))
    for name in sorted(stalled_prev - stalled_now):
        out.append(("host.collector.recovered", {"collector": name}))
    new_state["stalled_collectors"] = sorted(stalled_now)

    return new_state, out


# ---------- Snapshot handler (existing functionality preserved) -------------

def _project_snapshot(event: Event, instance_id: str) -> list[Event]:
    current = event.extra.get("snapshots") or {}
    previous = storage.get_host_snapshots(instance_id)

    # First-seen process detection. The agent's `processes` snapshot lists
    # current procs; we carry a monotonically-growing `seen_process_comms`
    # set in stored snapshots (the agent never sends this — projection-owned).
    first_seen_extras: list[dict[str, Any]] = []
    prev_seen = set((previous or {}).get("seen_process_comms") or [])
    cur_comms = {p.get("comm") for p in current.get("processes") or [] if p.get("comm")}
    # Suppress baseline floods. TWO baseline cases must stay silent:
    #   (a) first-ever snapshot for a host (previous is None),
    #   (b) existing host where the seen-set machinery just landed
    #       (previous exists but `seen_process_comms` was missing — that's
    #       what a v0.2 → v1.0 agent/code upgrade looks like).
    prev_had_seen_set = (
        previous is not None and "seen_process_comms" in (previous or {})
    )
    if prev_had_seen_set and cur_comms:
        for comm in sorted(cur_comms - prev_seen):
            first_seen_extras.append({"comm": comm})
    if cur_comms or prev_seen:
        current = {**current, "seen_process_comms": sorted(prev_seen | cur_comms)}

    storage.set_host_snapshots(
        instance_id, current, event.event_time or datetime.now(timezone.utc),
    )
    if previous is None:
        return []
    derived = [
        _make_derived(event, instance_id, action, extra)
        for action, extra in diff_snapshots(previous, current)
    ]
    for fe in first_seen_extras:
        derived.append(_make_derived(event, instance_id, "host.process.first_seen", fe))
    return derived


# ---------- Derived event helper -------------------------------------------

def _make_derived(parent: Event, instance_id: str, action: str, extra: dict[str, Any]) -> Event:
    return Event(
        source=Source(module=_MODULE, vendor="aws", account=parent.source.account,
                      region=parent.source.region, transport=Transport.queue),
        event_time=datetime.now(timezone.utc),
        category=Category.host,
        action=action,
        # `outcome=success` for "good news" transitions, failure for the rest.
        outcome=(Outcome.success if action.endswith(("recovered", "first_seen", "normal"))
                 else Outcome.failure),
        target=Target(id=instance_id, type="ec2.instance", name=parent.target.name),
        extra={"instance_id": instance_id, **extra},
        raw={"derived": "host-state-diff", "instance_id": instance_id},
    )
