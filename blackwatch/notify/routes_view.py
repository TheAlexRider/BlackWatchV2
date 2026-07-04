"""Notification-routes view.

The user's mental model on /notifications is:

  For each MODULE I care about, I have zero or more ROUTES.
  A route = "when a matching event fires, send it to this channel."

A route maps to exactly one row in notification_rules. The rule's match tree
is one of:
  * severity + module      — a simple by-module route
  * arbitrary condition    — an advanced custom rule (rendered under
                             the "custom" bucket in the UI)

This module walks all notification_rules, extracts the target module (if any),
and returns a grouped view for the /notifications page. It also handles the
create/update path for simple routes — the UI never has to build a Condition
tree by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .. import storage
from ..event import _SEVERITY_ORDER

# Curated module catalog — same list the UI shows so unrouted modules
# remain visible as coverage gaps.
MODULE_CATALOG: list[dict[str, str]] = [
    {"key": "aws.rds",        "label": "AWS RDS",         "blurb": "PostgreSQL / RDS Proxy auth + query events"},
    {"key": "aws.cloudtrail", "label": "AWS CloudTrail",  "blurb": "IAM changes, console logins, key events"},
    {"key": "aws.s3",         "label": "AWS S3",          "blurb": "Bucket policy / ACL / public-access changes"},
    {"key": "aws.posture",    "label": "AWS Posture",     "blurb": "Drift alerts against your posture baseline"},
    {"key": "vpn.openvpn",    "label": "OpenVPN",         "blurb": "Client connects, disconnects, failed logins"},
    {"key": "ec2.host",       "label": "EC2 Hosts",       "blurb": "Agent-driven host events (login, sudo, file)"},
    {"key": "ecs.probe",      "label": "ECS Probes",      "blurb": "Container probe findings (ClamAV, config)"},
    {"key": "cert",           "label": "TLS Certificates","blurb": "Cert expiry warnings"},
]

CUSTOM_BUCKET_KEY = "__custom__"


# ---- match-tree parsing --------------------------------------------------

def _extract_module_from_match(match: dict[str, Any] | None) -> str | None:
    """Return the target module of a rule's match tree if it can be
    unambiguously determined. Handles the shapes the routes UI produces:
      {all: [{field: source.module, op: equals, value: X}, ...]}
      {field: source.module, op: equals, value: X}
    Anything else (multiple modules, `in` list, `not`, `any`) returns None →
    the rule shows up under the custom bucket."""
    if not isinstance(match, dict):
        return None
    if match.get("field") == "source.module" and match.get("op") == "equals":
        val = match.get("value")
        if isinstance(val, str):
            return val
    for clause in match.get("all") or []:
        m = _extract_module_from_match(clause)
        if m is not None:
            return m
    # `any`, `not` and other shapes: too ambiguous to attribute to one module.
    return None


def _extract_severities(match: dict[str, Any] | None) -> list[str]:
    """Pull the severity `in [...]` clause from a match tree, if any.
    Returns an empty list if severity isn't constrained."""
    if not isinstance(match, dict):
        return []
    if match.get("field") == "severity":
        if match.get("op") == "in" and isinstance(match.get("value"), list):
            return [str(v) for v in match["value"]]
        if match.get("op") == "equals" and isinstance(match.get("value"), str):
            return [match["value"]]
    for clause in match.get("all") or []:
        sevs = _extract_severities(clause)
        if sevs:
            return sevs
    return []


def _rule_kind(match: dict[str, Any] | None) -> str:
    """`simple` if the rule can be edited with the route mini-form (module +
    severity + channel), `custom` otherwise."""
    if not isinstance(match, dict):
        return "custom"
    clauses = match.get("all")
    if not isinstance(clauses, list):
        # A bare single-clause rule counts as simple only if it's a module or
        # severity clause we understand.
        clauses = [match]
    for c in clauses:
        if not isinstance(c, dict):
            return "custom"
        field = c.get("field")
        op = c.get("op")
        if field == "source.module" and op == "equals":
            continue
        if field == "severity" and op == "in":
            continue
        # Anything else (action contains, category in, tags, negations…) →
        # too complex for the mini-form; render as custom.
        return "custom"
    return "simple"


# ---- match-tree construction ---------------------------------------------

def build_simple_match(module: str, severities: list[str]) -> dict[str, Any]:
    """Build the canonical match tree for a simple route."""
    valid = [s for s in severities if s in _SEVERITY_ORDER]
    if not valid:
        raise ValueError("at least one valid severity required")
    if module:
        return {
            "all": [
                {"field": "source.module", "op": "equals", "value": module},
                {"field": "severity", "op": "in", "value": valid},
            ]
        }
    # Rare: severity-only routes (no module scope) — not exposed in the UI
    # today but we accept them so the mini-form doesn't have to special-case.
    return {"field": "severity", "op": "in", "value": valid}


# ---- public shape --------------------------------------------------------

def list_routes() -> dict[str, Any]:
    """Return the whole routes view in one shot:

        {
          "buckets": [
            { "module": "aws.rds", "label": "AWS RDS", "blurb": "...",
              "routes": [ {rule_row}, ... ] },
            ...
            { "module": "__custom__", "label": "Custom", "routes": [...] },
          ],
          "coverage": {"routed": N, "total": M},
        }
    """
    try:
        all_rules = storage.list_notification_rules()
    except Exception:
        all_rules = []
    now_utc = datetime.utcnow()

    # Bucket rules by their extracted module. Anything without one lands in
    # the custom bucket.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in all_rules:
        module = _extract_module_from_match(r.get("match"))
        key = module if module else CUSTOM_BUCKET_KEY
        grouped.setdefault(key, []).append(_route_row(r, now_utc))

    buckets: list[dict[str, Any]] = []
    routed = 0
    for spec in MODULE_CATALOG:
        rows = grouped.get(spec["key"], [])
        if rows:
            routed += 1
        buckets.append({
            "module": spec["key"],
            "label": spec["label"],
            "blurb": spec["blurb"],
            "routes": rows,
        })

    # Custom bucket always at the end.
    buckets.append({
        "module": CUSTOM_BUCKET_KEY,
        "label": "Custom / advanced",
        "blurb": "Rules with conditions that don't map to a single module — "
                 "e.g. action-contains, cross-module filters.",
        "routes": grouped.get(CUSTOM_BUCKET_KEY, []),
    })

    return {
        "buckets": buckets,
        "coverage": {"routed": routed, "total": len(MODULE_CATALOG)},
    }


def _route_row(rule: dict[str, Any], now_utc: datetime) -> dict[str, Any]:
    silence_until = rule.get("silence_until")
    silenced = bool(silence_until) and silence_until.replace(tzinfo=None) > now_utc if silence_until else False
    return {
        "id": rule["id"],
        "name": rule.get("name"),
        "enabled": bool(rule.get("enabled")),
        "channel": (rule.get("channels") or [None])[0],
        "channels": rule.get("channels") or [],
        "severities": _extract_severities(rule.get("match")),
        "kind": _rule_kind(rule.get("match")),
        "silence_until": silence_until.isoformat() if silence_until else None,
        "silenced": silenced,
        "match": rule.get("match") or {},
    }


# ---- create / update -----------------------------------------------------

def upsert_simple_route(
    *,
    rule_id: str | None,
    module: str,
    severities: list[str],
    channel: str,
    enabled: bool = True,
) -> str:
    """Create-or-update a simple route. Returns the rule id."""
    if not module:
        raise ValueError("module required")
    if not channel:
        raise ValueError("channel required")
    match = build_simple_match(module, severities)
    rid = rule_id or str(uuid.uuid4())
    # A stable, human-readable rule name so the advanced rules table stays
    # legible. `route:<module>:<sev-set>` — no `auto:` prefix (there's no
    # longer a special "auto" concept; every route is a first-class rule).
    sev_tag = "+".join(sorted(severities))
    name = f"route:{module}:{sev_tag}" if severities else f"route:{module}"
    storage.upsert_notification_rule(
        rule_id=rid,
        name=name,
        enabled=enabled,
        match=match,
        channels=[channel],
        throttle_seconds=0,
        priority=50,
    )
    return rid
