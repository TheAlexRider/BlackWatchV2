"""Canonical notification ownership and coverage reporting.

This module deliberately contains no database or delivery imports. The
profile catalog is the source of truth; routing cards and the routes view
derive their module lists from it so the UI cannot silently drift from the
supported event surface.
"""

from __future__ import annotations

from typing import Any

from .profiles import NOTIFICATION_CATALOG, profile_id


_ICONS = {
    "ec2.host": "server",
    "aws.rds": "database",
    "aws.iam": "shield",
    "aws.s3": "archive",
    "aws.api_gateway": "route",
    "aws.posture": "eye",
    "aws.backup": "archive-restore",
    "aws.efs": "hard-drive",
    "aws.network": "network",
    "aws.secrets": "key-round",
    "aws.compute": "cpu",
    "aws.storage": "database-backup",
    "vpn.openvpn": "network",
    "ecs.probe": "activity",
    "cert": "key-round",
    "ueba": "scan-search",
    "findings": "triangle-alert",
}

_MODULE_ALIASES = {
    "aws.iam": {"aws.iam", "aws.cloudtrail"},
}


def canonical_module_keys() -> list[str]:
    return [str(module["key"]) for module in NOTIFICATION_CATALOG]


def module_for_event_kind(event_kind: str) -> str | None:
    for module in NOTIFICATION_CATALOG:
        if any(
            event.get("key") == event_kind
            or (module.get("key") == "ueba" and event.get("key") == "<category>.anomaly.first_seen_*"
                and (event_kind == "ueba.anomaly" or ".anomaly.first_seen_" in str(event_kind)))
            or (module.get("key") == "findings" and event.get("key") == "<finding>.detected"
                and str(event_kind).startswith("finding.") and str(event_kind).endswith(".detected"))
            for event in module.get("events") or []
        ):
            return str(module["key"])
    return None


def _module_blurb(module: dict[str, Any]) -> str:
    return str(module.get("description") or "Supported BlackWatch notification events.")


def _build_module_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": module["key"],
            "label": module["label"],
            "blurb": _module_blurb(module),
            "event_count": len(module.get("events") or []),
            "content_status": str(module.get("content_status") or "generic"),
            "content_rollout_stage": str(module.get("content_rollout_stage") or "backlog"),
            "content_gap_count": int(module.get("content_gap_count") or 0),
        }
        for module in NOTIFICATION_CATALOG
    ]


def _build_module_cards() -> list[dict[str, Any]]:
    return [
        {
            **module,
            "icon": _ICONS.get(module["key"], "bell"),
        }
        for module in _build_module_catalog()
    ]


# Public compatibility shapes. Both are generated from NOTIFICATION_CATALOG.
MODULE_CATALOG = _build_module_catalog()
MODULE_CARDS = _build_module_cards()


def _walk_match(match: Any) -> list[dict[str, Any]]:
    if not isinstance(match, dict):
        return []
    leaves: list[dict[str, Any]] = []
    if "field" in match:
        leaves.append(match)
    for key in ("all", "any"):
        for clause in match.get(key) or []:
            leaves.extend(_walk_match(clause))
    if isinstance(match.get("not"), dict):
        leaves.extend(_walk_match(match["not"]))
    return leaves


def _rule_covers_event(rule: dict[str, Any], module: str, event_kind: str) -> bool:
    if str(rule.get("id") or "").startswith("profile:"):
        return False
    leaves = _walk_match(rule.get("match"))
    action_leaves = [leaf for leaf in leaves if leaf.get("field") == "action"]
    if action_leaves:
        for leaf in action_leaves:
            value = leaf.get("value")
            values = value if isinstance(value, list) else [value]
            if event_kind in {str(item) for item in values}:
                return True
        return False
    return any(
        leaf.get("field") == "source.module"
        and leaf.get("op") == "equals"
        and leaf.get("value") in _MODULE_ALIASES.get(module, {module})
        for leaf in leaves
    )


def _rule_severities(rule: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for leaf in _walk_match(rule.get("match")):
        if leaf.get("field") != "severity":
            continue
        raw = leaf.get("value")
        values.extend(str(item) for item in (raw if isinstance(raw, list) else [raw]) if item)
    return list(dict.fromkeys(values))


def _is_silenced(value: Any) -> bool:
    if not value:
        return False
    try:
        from datetime import datetime, timezone

        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


def build_coverage(
    saved_profiles: list[dict[str, Any]] | None,
    notification_rules: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return event-level coverage without changing any delivery setting."""
    profiles = {str(item.get("id")): item for item in (saved_profiles or [])}
    rules = notification_rules or []
    output: list[dict[str, Any]] = []

    for module in NOTIFICATION_CATALOG:
        event_rows: list[dict[str, Any]] = []
        for event in module["events"]:
            module_key = str(module["key"])
            event_kind = str(event["key"])
            pid = profile_id(module_key, event_kind)
            saved = profiles.get(pid)
            matching_rules = [
                rule for rule in rules
                if _rule_covers_event(rule, module_key, event_kind)
                and (rule.get("channels") or [])
            ]
            active_rules = [rule for rule in matching_rules if bool(rule.get("enabled")) and not _is_silenced(rule.get("silence_until"))]
            covered_severities: list[str] = []
            if saved is not None:
                covered_severities = [str(item) for item in (saved.get("severities") or [])]
                if _is_silenced(saved.get("silence_until")) or not bool(saved.get("enabled")):
                    state = "muted"
                elif saved.get("channels"):
                    state = "configured"
                else:
                    state = "unconfigured"
            elif active_rules:
                state = "fallback"
                for rule in active_rules:
                    covered_severities.extend(_rule_severities(rule))
                covered_severities = list(dict.fromkeys(covered_severities))
            elif matching_rules:
                state = "muted"
                for rule in matching_rules:
                    covered_severities.extend(_rule_severities(rule))
                covered_severities = list(dict.fromkeys(covered_severities))
            else:
                state = "unconfigured"

            default_severities = [str(item) for item in event.get("default_severities") or []]
            high_critical_gap = bool(set(default_severities) & {"high", "critical"}) and not bool(
                set(covered_severities) & {"high", "critical"}
            )
            event_rows.append({
                "event_kind": event_kind,
                "label": event["label"],
                "description": event["description"],
                "default_severities": default_severities,
                "profile_id": pid,
                "state": state,
                "covered_severities": covered_severities,
                "high_critical_gap": high_critical_gap,
                "content_status": str(event.get("content_status") or "generic"),
                "rollout_stage": str(event.get("rollout_stage") or "backlog"),
                "content_gap": str(event.get("content_status") or "generic") == "generic",
            })

        counts = {state: sum(row["state"] == state for row in event_rows) for state in ("configured", "fallback", "muted", "unconfigured")}
        output.append({
            **next(item for item in MODULE_CATALOG if item["key"] == module["key"]),
            "counts": counts,
            "gap_count": sum(row["high_critical_gap"] for row in event_rows),
            "content_gap_count": sum(row["content_gap"] for row in event_rows),
            "events": event_rows,
        })
    return output
