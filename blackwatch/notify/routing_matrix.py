"""Module-cards notification routing.

The user's mental model is "for each module (RDS, VPN, IAM etc), pick a channel
and a severity threshold." Under the hood each card is a single row in the
existing notification_rules table with a well-known name (`auto:<module>`) and
a deterministic id derived from the module id. Dispatch stays on the same rule
engine — cards are just a friendlier UI over the same data.

Nothing here changes existing behavior for hand-written rules; they keep firing
alongside cards. If the same event matches both a card and a manual rule, both
fire (each channel dedupes on fingerprint per the standard path).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import storage

_AUTO_PREFIX = "auto:"
# Arbitrary but stable namespace so uuid5(module) is idempotent across restarts.
_AUTO_NAMESPACE = uuid.UUID("6f8b1d0e-d0b0-4a5f-b1a5-1a3e2f9c9c9c")


# Curated module list. Order = display order in the UI. `key` is the event
# source.module id; `label` is the friendly name; `icon` is a hint the UI can
# map to a lucide icon name.
MODULE_CARDS: list[dict[str, str]] = [
    {"key": "aws.rds",        "label": "AWS RDS",         "icon": "database",  "blurb": "PostgreSQL / RDS Proxy auth + query events"},
    {"key": "aws.cloudtrail", "label": "AWS CloudTrail",  "icon": "shield",    "blurb": "IAM changes, console logins, key events"},
    {"key": "aws.s3",         "label": "AWS S3",          "icon": "archive",   "blurb": "Bucket policy / ACL / public-access changes"},
    {"key": "aws.posture",    "label": "AWS Posture",     "icon": "eye",       "blurb": "Drift alerts against your posture baseline"},
    {"key": "vpn.openvpn",    "label": "OpenVPN",         "icon": "network",   "blurb": "Client connects, disconnects, failed logins"},
    {"key": "ec2.host",       "label": "EC2 Hosts",       "icon": "server",    "blurb": "Agent-driven host events (login, sudo, file)"},
    {"key": "ecs.probe",      "label": "ECS Probes",      "icon": "activity",  "blurb": "Container probe findings (ClamAV, config)"},
    {"key": "cert",           "label": "TLS Certificates","icon": "key-round", "blurb": "Cert expiry warnings"},
]


# Severity threshold presets. Each preset expands to a `severity in [...]`
# clause. Ordering: strictest first.
THRESHOLDS: list[dict[str, Any]] = [
    {
        "key": "critical",
        "label": "Only critical",
        "includes": ["critical"],
    },
    {
        "key": "high",
        "label": "Critical + high (recommended)",
        "includes": ["critical", "high"],
    },
    {
        "key": "medium",
        "label": "Everything ≥ medium",
        "includes": ["critical", "high", "medium"],
    },
    {
        "key": "low",
        "label": "Everything except info",
        "includes": ["critical", "high", "medium", "low"],
    },
]

_DEFAULT_THRESHOLD = "high"


@dataclass
class Card:
    module: str
    label: str
    icon: str
    blurb: str
    enabled: bool = False
    channel: str | None = None
    threshold: str = _DEFAULT_THRESHOLD
    silence_until: datetime | None = None
    rule_id: str | None = None


# --- ID / name / match helpers ---------------------------------------------

def card_rule_id(module: str) -> str:
    return str(uuid.uuid5(_AUTO_NAMESPACE, f"auto:{module}"))


def _card_rule_name(module: str) -> str:
    return f"{_AUTO_PREFIX}{module}"


def is_auto_rule_name(name: str | None) -> bool:
    return bool(name) and name.startswith(_AUTO_PREFIX)


def _build_match(module: str, threshold: str) -> dict[str, Any]:
    return {
        "all": [
            {"field": "source.module", "op": "equals", "value": module},
            {"field": "severity", "op": "in",
             "value": _severities_for_threshold(threshold)},
        ]
    }


def _severities_for_threshold(threshold: str) -> list[str]:
    for t in THRESHOLDS:
        if t["key"] == threshold:
            return list(t["includes"])
    return list(THRESHOLDS[1]["includes"])


def _threshold_from_match(match: dict[str, Any]) -> str:
    """Reverse-engineer the threshold key from a stored match. Falls back to
    the default if the match wasn't produced by this module (someone hand-
    edited the rule via the advanced UI)."""
    clauses = (match or {}).get("all") or []
    for c in clauses:
        if c.get("field") == "severity" and c.get("op") == "in":
            included = set(c.get("value") or [])
            for t in THRESHOLDS:
                if set(t["includes"]) == included:
                    return t["key"]
    return _DEFAULT_THRESHOLD


# --- Public API -------------------------------------------------------------

def list_cards() -> list[dict[str, Any]]:
    """Return one entry per curated module. Modules the user has never touched
    come back with their defaults (disabled, no channel)."""
    try:
        rules_by_id = {r["id"]: r for r in storage.list_notification_rules()}
    except Exception:
        rules_by_id = {}
    out: list[dict[str, Any]] = []
    for spec in MODULE_CARDS:
        module = spec["key"]
        rule = rules_by_id.get(card_rule_id(module))
        card = Card(
            module=module,
            label=spec["label"],
            icon=spec["icon"],
            blurb=spec["blurb"],
        )
        if rule is not None:
            channels = rule.get("channels") or []
            card.rule_id = rule["id"]
            card.enabled = bool(rule.get("enabled"))
            card.channel = channels[0] if channels else None
            card.threshold = _threshold_from_match(rule.get("match") or {})
            card.silence_until = rule.get("silence_until")
        out.append(_card_to_dict(card))
    return out


def save_card(
    module: str,
    enabled: bool,
    channel: str | None,
    threshold: str,
) -> dict[str, Any]:
    """Persist a card. Empty channel = delete the rule (card is off)."""
    if not any(m["key"] == module for m in MODULE_CARDS):
        raise ValueError(f"unknown module {module!r}")
    if threshold not in {t["key"] for t in THRESHOLDS}:
        raise ValueError(f"invalid threshold {threshold!r}")

    rule_id = card_rule_id(module)
    if not channel:
        try:
            storage.delete_notification_rule(rule_id)
        except Exception:
            pass
    else:
        storage.upsert_notification_rule(
            rule_id=rule_id,
            name=_card_rule_name(module),
            enabled=enabled,
            match=_build_match(module, threshold),
            channels=[channel],
            throttle_seconds=0,
            priority=50,  # cards outrank hand-crafted rules by default
        )
    _reload_notifier()
    return _find_card(module)


def silence_card(module: str, hours: int) -> dict[str, Any]:
    """Silence a card for N hours. `hours <= 0` clears the silence."""
    if not any(m["key"] == module for m in MODULE_CARDS):
        raise ValueError(f"unknown module {module!r}")
    rule_id = card_rule_id(module)
    until: datetime | None
    if hours > 0:
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
    else:
        until = None
    try:
        storage.set_notification_rule_silence(rule_id, until)
    except Exception:
        pass
    _reload_notifier()
    return _find_card(module)


def test_card(module: str) -> dict[str, Any]:
    """Fire a synthetic test event through the card's channel."""
    card = _find_card(module)
    if not card:
        return {"status": "unknown_module"}
    channel = card.get("channel")
    if not channel:
        return {"status": "no_channel"}
    from . import router as router_module
    return router_module.get_notifier().send_test(channel)


# --- helpers ----------------------------------------------------------------

def _card_to_dict(card: Card) -> dict[str, Any]:
    return {
        "module": card.module,
        "label": card.label,
        "icon": card.icon,
        "blurb": card.blurb,
        "enabled": card.enabled,
        "channel": card.channel,
        "threshold": card.threshold,
        "silence_until": card.silence_until.isoformat() if card.silence_until else None,
        "rule_id": card.rule_id,
    }


def _find_card(module: str) -> dict[str, Any]:
    for c in list_cards():
        if c["module"] == module:
            return c
    return {}


def _reload_notifier() -> None:
    from . import router as router_module
    try:
        router_module.get_notifier().reload_rules()
    except Exception:
        pass
