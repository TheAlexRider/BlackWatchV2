from datetime import datetime, timedelta, timezone

from blackwatch.event import Event, Source, Transport
from blackwatch.services import projection


def _result(status: str, *, target_id: str = "target-1", when: datetime | None = None) -> Event:
    return Event(
        source=Source(module="ecs.probe", transport=Transport.api),
        event_time=when or datetime.now(timezone.utc),
        action="service.probe.result",
        extra={
            "target_id": target_id,
            "vpc": "prod",
            "name": "keycloak",
            "tier": "http_alive",
            "status": status,
            "error": "timed out" if status == "unknown" else None,
            "result_extra": {"http_status": None} if status == "unknown" else {"http_status": 200},
        },
    )


def test_sustained_unknown_emits_target_unknown_transition(monkeypatch):
    state: dict[str, dict] = {}
    saved: list[dict] = []

    monkeypatch.setattr(projection.storage, "get_service_status", lambda target_id: state.get(target_id))
    monkeypatch.setattr(
        projection.storage,
        "get_probe_target",
        lambda target_id: {"id": target_id, "tags": {"env": "prod"}},
    )

    def save(target_id, **kwargs):
        state[target_id] = {"status": kwargs["status"], **kwargs}
        saved.append(kwargs)

    monkeypatch.setattr(projection.storage, "upsert_service_status", save)

    first = projection.project(_result("unknown", when=datetime(2026, 8, 14, tzinfo=timezone.utc)))
    second = projection.project(_result("unknown", when=datetime(2026, 8, 14, 0, 10, tzinfo=timezone.utc)))

    assert first == []
    assert [event.action for event in second] == ["service.unknown"]
    assert saved[-1]["extra"]["unknown_since"]
    assert second[0].extra["service_name"] == "keycloak"
    assert second[0].extra["error_signal"] == "timed out"
    assert second[0].extra["monitoring_method"] == "service probe"
    assert second[0].extra["monitoring_impact"]
    assert second[0].extra["last_report"]
    assert second[0].extra["unknown_seconds"] >= 600


def test_recovery_from_unknown_includes_unknown_duration(monkeypatch):
    unknown_since = datetime.now(timezone.utc) - timedelta(minutes=10)
    state = {
        "target-1": {
            "status": "unknown",
            "consecutive_fails": 0,
            "consecutive_success": 0,
            "down_since": None,
            "extra": {"unknown_since": unknown_since.isoformat(), "unknown_alerted": True},
        }
    }
    saved: list[dict] = []

    monkeypatch.setattr(projection.storage, "get_service_status", lambda target_id: state.get(target_id))
    monkeypatch.setattr(
        projection.storage,
        "get_probe_target",
        lambda target_id: {"id": target_id, "tags": {"env": "prod"}},
    )
    monkeypatch.setattr(
        projection.storage,
        "upsert_service_status",
        lambda target_id, **kwargs: (state.update({target_id: {"status": kwargs["status"], **kwargs}}), saved.append(kwargs)),
    )

    projection.project(_result("up", when=datetime.now(timezone.utc)))
    recovered = projection.project(_result("up", when=datetime.now(timezone.utc) + timedelta(minutes=1)))

    assert [event.action for event in recovered] == ["service.up"]
    assert recovered[0].extra["unknown_seconds"] >= 600
    assert recovered[0].extra["downtime_seconds"] == 0
    assert recovered[0].extra["service_name"] == "keycloak"
    assert "monitoring recovered" in recovered[0].extra["message"].lower()
