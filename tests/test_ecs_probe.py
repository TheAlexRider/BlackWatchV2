"""ECS probe adapter + AWS-side aggregation. No DB."""

from blackwatch.connectors.aws_ecs import _aggregate_health, _running_status, _running_windows
from blackwatch.modules.base import IngestContext
from blackwatch.modules.ecs_probe import EcsProbeAdapter


def _ctx():
    return IngestContext(module="ecs.probe", transport="api")


def _report(results):
    return {
        "kind": "ecs_probe_report",
        "vpc": "dev",
        "agent_version": "1.0",
        "observed_at": "2026-06-03T12:00:00Z",
        "results": results,
    }


# ---------- adapter ----------

def test_adapter_emits_heartbeat_and_results():
    rpt = _report([
        {"target_id": "t-1", "name": "ai-gateway-api", "tier": "http_alive",
         "status": "up", "latency_ms": 42, "error": None, "extra": {}},
        {"target_id": "t-2", "name": "database-logs", "tier": "tcp",
         "status": "down", "latency_ms": None, "error": "refused", "extra": {}},
    ])
    events = EcsProbeAdapter().parse(rpt, _ctx())
    actions = [e.action for e in events]
    assert actions.count("probe.agent.heartbeat") == 1
    assert actions.count("service.probe.result") == 2
    hb = next(e for e in events if e.action == "probe.agent.heartbeat")
    assert hb.extra["vpc"] == "dev"
    assert hb.extra["result_count"] == 2

    down = next(e for e in events
                if e.action == "service.probe.result" and e.extra["status"] == "down")
    assert down.extra["target_id"] == "t-2"
    assert down.outcome.value == "failure"
    assert down.extra["error"] == "refused"


def test_adapter_ignores_non_report():
    assert EcsProbeAdapter().parse({"kind": "something_else"}, _ctx()) == []


def test_adapter_skips_results_without_target_id():
    rpt = _report([{"name": "no-id", "status": "up"}])  # missing target_id
    events = EcsProbeAdapter().parse(rpt, _ctx())
    actions = [e.action for e in events]
    assert "probe.agent.heartbeat" in actions
    assert "service.probe.result" not in actions


def test_adapter_handles_unknown_status():
    rpt = _report([{"target_id": "t-x", "name": "x", "tier": "ecs_health",
                    "status": "unknown", "latency_ms": None, "error": None, "extra": {}}])
    events = EcsProbeAdapter().parse(rpt, _ctx())
    result = next(e for e in events if e.action == "service.probe.result")
    assert result.extra["status"] == "unknown"
    assert result.outcome.value == "failure"  # only 'up' is success in the adapter


# ---------- AWS-side aggregation ----------

def test_aggregate_health_all_healthy_is_up():
    tasks = [
        {"containers": [{"healthStatus": "HEALTHY"}]},
        {"containers": [{"healthStatus": "HEALTHY"}]},
    ]
    status, extra = _aggregate_health(tasks)
    assert status == "up"
    assert extra["healthy"] == 2 and extra["unhealthy"] == 0


def test_aggregate_health_any_unhealthy_some_healthy_is_degraded():
    tasks = [
        {"containers": [{"healthStatus": "HEALTHY"}]},
        {"containers": [{"healthStatus": "UNHEALTHY"}]},
    ]
    status, _ = _aggregate_health(tasks)
    assert status == "degraded"


def test_aggregate_health_all_unhealthy_is_down():
    tasks = [{"containers": [{"healthStatus": "UNHEALTHY"}]}] * 2
    status, _ = _aggregate_health(tasks)
    assert status == "down"


def test_aggregate_health_no_tasks_is_down():
    status, extra = _aggregate_health([])
    assert status == "down"
    assert extra["total_tasks"] == 0


def test_aggregate_health_all_unknown_is_unknown():
    """If no container has a healthStatus AWS recognized (no healthCheck
    configured), we must say 'unknown' — not lie 'up'."""
    tasks = [{"containers": [{"healthStatus": "UNKNOWN"}]}] * 3
    status, _ = _aggregate_health(tasks)
    assert status == "unknown"


# ---------- runningCount smoothing ----------

def test_running_status_at_desired_is_up():
    _running_windows.clear()
    s, extra = _running_status("t-1", running=2, desired=2, now=1000.0, smoothing_seconds=300)
    assert s == "up"
    assert extra["running"] == 2 and extra["desired"] == 2


def test_running_status_briefly_below_is_degraded_not_down():
    """A single below-desired sample isn't 'down' — Fargate Spot interrupts
    routinely. Should produce a transient 'degraded' until the smoothing
    window has been fully below."""
    _running_windows.clear()
    s, _ = _running_status("t-2", running=1, desired=2, now=1000.0, smoothing_seconds=300)
    assert s == "degraded"


def test_running_status_sustained_below_becomes_down():
    _running_windows.clear()
    # Fill enough samples that, after the window cutoff trims older entries,
    # the kept span is still >= smoothing_seconds. 30s spacing × ~20 samples
    # gives plenty of headroom regardless of cutoff timing.
    for offset in range(0, 600, 30):
        _running_status("t-3", running=0, desired=2, now=1000.0 + offset, smoothing_seconds=300)
    s, _ = _running_status("t-3", running=0, desired=2, now=1600.0, smoothing_seconds=300)
    assert s == "down"


def test_running_status_recovers_to_up_immediately():
    """If runningCount returns to desired, we don't need smoothing on the way
    UP — recover instantly."""
    _running_windows.clear()
    for offset in range(0, 600, 30):
        _running_status("t-4", running=0, desired=2, now=1000.0 + offset, smoothing_seconds=300)
    s, _ = _running_status("t-4", running=2, desired=2, now=1600.0, smoothing_seconds=300)
    assert s == "up"
