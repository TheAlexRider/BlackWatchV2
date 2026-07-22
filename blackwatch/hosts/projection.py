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
from .. import perf_alerts
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
    # FIM Part 1 — update baseline + append history rows for every change.
    if event.action in _FIM_CHANGE_ACTIONS:
        return _project_fim_change(event, instance_id)
    if event.action == "host.fim.coverage":
        return _project_fim_coverage(event, instance_id)
    return []


_FIM_CHANGE_ACTIONS = frozenset({
    "host.fim.created",
    "host.fim.modified",
    "host.fim.deleted",
    "host.fim.perm_changed",
    "host.fim.owner_changed",
})


def _project_fim_change(event: Event, instance_id: str) -> list[Event]:
    """One FIM change event arrived. Append to fim_history (always), then
    refresh the current baseline row (or delete it on `deleted`).

    Never emits derived events — the change event itself is the signal. The
    rules engine + notifier already pick it up; no second-order amplification."""
    e = event.extra or {}
    path = e.get("path")
    if not path:
        return []
    when = event.event_time or datetime.now(timezone.utc)
    change_type = e.get("change_type", "modified")

    # Part 3: actor fields come through extra.actor when the agent's audit
    # reader had a fresh hit for this path. Best-effort — missing fields
    # are normal (auditd absent, change detected by periodic scanner, etc).
    actor = e.get("actor") if isinstance(e.get("actor"), dict) else {}
    storage.insert_fim_history(
        instance_id,
        path,
        changed_at=when,
        change_type=change_type,
        sha256_before=e.get("sha256_before"),
        sha256_after=e.get("sha256_after"),
        size_before=_safe_int(e.get("size_before")),
        size_after=_safe_int(e.get("size_after")),
        perm_before=_safe_int(e.get("perm_before")),
        perm_after=_safe_int(e.get("perm_after")),
        owner_before=e.get("owner_before"),
        owner_after=e.get("owner_after"),
        event_id=event.event_id,
        detection=e.get("detection"),
        actor_uid=_safe_int(actor.get("uid")),
        actor_gid=_safe_int(actor.get("gid")),
        actor_pid=_safe_int(actor.get("pid")),
        actor_comm=_safe_str(actor.get("comm")),
        actor_exe=_safe_str(actor.get("exe")),
        actor_proctitle=_safe_str(actor.get("proctitle")),
    )

    if change_type == "deleted":
        storage.delete_fim_baseline(instance_id, path)
        return []

    # Created / modified / perm_changed / owner_changed — update the baseline
    # to the new known-good. We only have full metadata when the after-state
    # is known; gracefully no-op if the agent shipped a partial change.
    sha256 = e.get("sha256_after")
    perm = _safe_int(e.get("perm_after"))
    size = _safe_int(e.get("size_after"))
    owner_after = e.get("owner_after") or ""
    if not sha256 or perm is None or size is None:
        return []
    try:
        uid_str, gid_str = owner_after.split(":", 1)
        owner_uid = int(uid_str)
        owner_gid = int(gid_str)
    except (ValueError, AttributeError):
        owner_uid = -1
        owner_gid = -1

    storage.upsert_fim_baseline(
        instance_id,
        path,
        sha256=sha256,
        size=size,
        perm=perm,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
        mtime=when,
        last_seen_at=when,
    )
    return []


def _project_fim_coverage(event: Event, instance_id: str) -> list[Event]:
    """Heartbeat-frequency coverage summary. Persist into fim_coverage so the
    UI can show 'tracking 324 files, last scan 3h ago' without scanning the
    full baseline table on every page load."""
    e = event.extra or {}
    when = event.event_time or datetime.now(timezone.utc)
    last_scan = e.get("last_full_scan_at")
    if isinstance(last_scan, str):
        try:
            last_scan_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
        except ValueError:
            last_scan_dt = None
    else:
        last_scan_dt = None

    configured_paths = e.get("configured_paths")
    if not isinstance(configured_paths, dict):
        configured_paths = None
    path_stats = e.get("path_stats")
    if not isinstance(path_stats, dict):
        path_stats = None
    storage.upsert_fim_coverage(
        instance_id,
        paths_configured=_safe_int(e.get("paths_configured")) or 0,
        files_tracked=_safe_int(e.get("files_tracked")) or 0,
        last_full_scan_at=last_scan_dt,
        last_scan_duration_ms=_safe_int(e.get("last_scan_duration_ms")),
        scan_errors=_safe_int(e.get("scan_errors")) or 0,
        updated_at=when,
        paths_inotify=_safe_int(e.get("paths_inotify")) or 0,
        paths_baseline_only=_safe_int(e.get("paths_baseline_only")) or 0,
        inotify_active=bool(e.get("inotify_active")),
        inotify_watch_count=_safe_int(e.get("inotify_watch_count")) or 0,
        auditd_active=bool(e.get("auditd_active")),
        configured_paths=configured_paths,
        path_stats=path_stats,
    )
    return []


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _safe_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    # Defensive cap so a malicious or buggy agent can't OOM the projection by
    # shipping a 50 MB "comm" field.
    return s[:512] if len(s) > 512 else s


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

    # User-configured threshold alerts — runs alongside the hardcoded
    # transitions above (95% memory etc.). Both can fire; built-in
    # alerts are the safety net, perf rules are the customizable layer.
    # The evaluator also dispatches directly to its bound channels, so
    # the user doesn't have to wire a separate notification rule.
    derived.extend(perf_alerts.evaluate(event))

    # Hourly metric rollup — powers the host detail page's chart. Memory %
    # and normalized CPU load % only. Disk isn't rolled up because it drifts
    # day-over-day, not by the minute — perf-alert threshold breach covers
    # that case, no chart to add signal. Failing the rollup must NEVER break
    # the projection or the alert path — swallow any exception.
    try:
        metrics = perf_alerts._extract_metrics(e)
        storage.upsert_host_metric_sample(
            instance_id,
            when,
            mem_pct=metrics.get("memory_pct"),
            cpu_pct=metrics.get("cpu_load_norm"),
        )
    except Exception:
        pass

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
