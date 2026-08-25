"""Persistence and compatibility services for Notification Studio profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Event
from . import channels as channels_module
from . import profiles as profile_model
from .model import Channel


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError("silence_until must be an ISO timestamp") from None
    return None


def _serialize(profile: dict[str, Any], *, source: str = "saved") -> dict[str, Any]:
    out = dict(profile)
    out["silence_until"] = _iso(out.get("silence_until"))
    out["updated_at"] = _iso(out.get("updated_at"))
    out["created_at"] = _iso(out.get("created_at"))
    out["source"] = source
    return out


def _saved_profile_rows() -> dict[str, dict[str, Any]]:
    try:
        return {row["id"]: row for row in storage.list_notification_profiles()}
    except Exception:
        return {}


def list_profiles() -> list[dict[str, Any]]:
    """Return every catalog item, including untouched default profiles."""
    saved = _saved_profile_rows()
    rows: list[dict[str, Any]] = []
    for module in profile_model.NOTIFICATION_CATALOG:
        for event in module["events"]:
            pid = profile_model.profile_id(module["key"], event["key"])
            row = saved.get(pid)
            if row is None:
                payload = {
                    "id": pid,
                    "module": module["key"],
                    "event_kind": event["key"],
                    "label": event["label"],
                    "description": event["description"],
                    "enabled": False,
                    "severities": event["default_severities"],
                    "channels": [],
                    "throttle_seconds": 0,
                    "digest_window_seconds": 0,
                    "content": event["defaults"],
                    "advanced_template": None,
                }
                normalized = profile_model.normalize_profile(payload)
                rows.append(_serialize(normalized, source="default"))
            else:
                normalized = profile_model.normalize_profile(row)
                normalized["created_at"] = row.get("created_at")
                normalized["updated_at"] = row.get("updated_at")
                rows.append(_serialize(normalized))
    return rows


def get_profile(profile_id: str) -> dict[str, Any] | None:
    return next((row for row in list_profiles() if row["id"] == profile_id), None)


def _profile_event(profile: dict[str, Any]) -> Event:
    return profile_model.build_preview_event(profile)


def render_preview(profile: dict[str, Any], channel_type: str = "slack") -> str:
    normalized = profile_model.normalize_profile(profile)
    event = _profile_event(normalized)
    channel = Channel(name="preview", type=channel_type, enabled=True, config={})
    return channels_module._render(channel, event, rule_template=normalized["message_template"])


def save_profile(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = profile_model.normalize_profile(payload)
    silence_until = _parse_datetime(normalized.get("silence_until"))
    storage.upsert_notification_profile(
        profile_id=normalized["id"], module=normalized["module"],
        event_kind=normalized["event_kind"], label=normalized["label"],
        description=normalized["description"], enabled=normalized["enabled"],
        severities=normalized["severities"], channels=normalized["channels"],
        throttle_seconds=normalized["throttle_seconds"],
        digest_window_seconds=normalized["digest_window_seconds"],
        silence_until=silence_until, content=normalized["content"],
        advanced_template=normalized["advanced_template"],
    )
    storage.upsert_notification_rule(
        rule_id=normalized["id"],
        name=f"profile:{normalized['module']}:{normalized['event_kind']}",
        enabled=normalized["enabled"],
        match=profile_model.build_profile_match(
            normalized["module"], normalized["event_kind"], normalized["severities"]
        ),
        channels=normalized["channels"],
        throttle_seconds=normalized["throttle_seconds"],
        priority=40,
        message_template=normalized["message_template"],
        digest_window_seconds=normalized["digest_window_seconds"],
    )
    storage.record_notification_profile_audit(
        normalized["id"],
        "save",
        "enabled=%s channels=%d advanced=%s"
        % (
            normalized["enabled"],
            len(normalized["channels"]),
            bool(normalized["advanced_template"]),
        ),
    )
    from . import router as notify_router
    notify_router.get_notifier().reload_rules()
    return get_profile(normalized["id"]) or _serialize(normalized)


def delete_profile(profile_id: str) -> None:
    storage.delete_notification_profile(profile_id)
    storage.delete_notification_rule(profile_id)
    storage.record_notification_profile_audit(profile_id, "delete")
    from . import router as notify_router
    notify_router.get_notifier().reload_rules()


def test_profile(profile_id: str) -> dict[str, Any]:
    profile = get_profile(profile_id)
    if profile is None:
        return {"status": "unknown_profile"}
    if not profile.get("channels"):
        return {"status": "no_channels", "profile_id": profile_id}
    event = _profile_event(profile)
    notifier = _notifier()
    outcomes: list[dict[str, Any]] = []
    for channel_name in profile["channels"]:
        channel = notifier.channels.get(channel_name)
        if channel is None or not channel.enabled:
            outcomes.append({"channel": channel_name, "status": "skipped"})
            continue
        ok, detail = channels_module.send(
            channel, event, rule_template=profile["message_template"]
        )
        outcomes.append({
            "channel": channel_name,
            "status": "sent" if ok else "error",
            "detail": detail,
        })
    return {"profile_id": profile_id, "status": "sent" if any(o["status"] == "sent" for o in outcomes) else "error", "outcomes": outcomes}


def _notifier():
    from . import router as notify_router
    notifier = notify_router.get_notifier()
    notifier.reload_channels()
    return notifier
