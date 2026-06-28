"""Channel delivery (Phase 2).

Pluggable channel types — slack, webhook, email, pagerduty, teams, discord —
each with a Jinja2-rendered message body and a default template per type.

Secrets are NEVER stored in channel config. Sensitive values are referenced
by env var name (e.g. `password_env: SMTP_PASS`, `routing_key_env: PD_KEY`);
this module reads the env at send time. Set the env var in docker-compose.

Sends are best-effort and never raise — failures are returned, so the worker
can record them and retry.
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText
from typing import Any

from jinja2 import Environment, StrictUndefined

from ..event import Event
from .model import Channel

_TIMEOUT = 10

# ---- Template presets per type ----------------------------------------------
#
# Each channel type ships a small set of named templates. The first one is the
# default; users can pick another (or write their own) from the UI's template
# picker. Keep the names stable — they're API contract once the picker reads
# them.
#
# Severity is often unset for routine telemetry. We bias toward NOT shouting
# "UNSCORED" — when severity is missing, the friendly templates just omit it.

_SEV_EMOJI = (
    "{% if event.severity == 'critical' %}🚨"
    "{% elif event.severity == 'high' %}⚠️"
    "{% elif event.severity == 'medium' %}🟡"
    "{% elif event.severity == 'low' %}🔵"
    "{% else %}🔔{% endif %}"
)

TEMPLATE_PRESETS: dict[str, list[dict[str, str]]] = {
    "slack": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain English, emoji per severity. Easy to scan in a channel. "
                     "Uses event.extra.message as the headline when present "
                     "(perf alerts, FIM events with rich descriptions).",
            "template": (
                # Headline: rich message if the event provides one, else the
                # raw action name. Most events set extra.message when they
                # have something more informative than the action label.
                f"{_SEV_EMOJI} *{{{{ event.extra.message or event.action }}}}*"
                # Actor block — for events caused by a person.
                "{% if event.actor.principal %} — `{{ event.actor.principal }}`{% endif %}"
                "{% if event.actor.source_ip %} from `{{ event.actor.source_ip }}`{% endif %}"
                # Target context — prefer role tag, then hostname, then ID.
                "{% if event.extra.tags and event.extra.tags.role %}"
                " on `{{ event.extra.tags.role }}`"
                "{% elif event.target.name %} on `{{ event.target.name }}`"
                "{% elif event.target.id %} on `{{ event.target.id }}`{% endif %}"
                "{% if event.severity %} _(severity: {{ event.severity }})_{% endif %}"
            ),
        },
        {
            "id": "detailed",
            "name": "Detailed",
            "blurb": "Multi-line with all key fields. Best for an alerts channel where each message stands alone.",
            "template": (
                f"{_SEV_EMOJI} *{{{{ event.extra.message or event.action }}}}*\n"
                "{% if event.actor.principal %}• *Who:* {{ event.actor.principal }}\n{% endif %}"
                "{% if event.actor.source_ip %}• *From:* {{ event.actor.source_ip }}\n{% endif %}"
                "• *When:* {{ event.event_time }}\n"
                "• *Target:* {{ event.target.name or event.target.id or '—' }}\n"
                "{% if event.extra.tags %}• *Tags:* "
                "{% for k, v in event.extra.tags.items() %}{{ k }}={{ v }}{% if not loop.last %}, {% endif %}{% endfor %}\n{% endif %}"
                "{% if event.severity %}• *Severity:* {{ event.severity }}\n{% endif %}"
                "{% if event.rule_matches %}• *Matched rules:* {{ event.rule_matches|join(', ') }}{% endif %}"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Single line, no fluff. Best for a noisy logs channel.",
            "template": (
                "{{ event.extra.message or event.action }}"
                "{% if event.actor.principal %} · {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} ({{ event.actor.source_ip }}){% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %} · {{ event.extra.tags.role }}{% endif %}"
            ),
        },
    ],
    "discord": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain English, emoji per severity. Uses extra.message when available.",
            "template": (
                f"{_SEV_EMOJI} **{{{{ event.extra.message or event.action }}}}**"
                "{% if event.actor.principal %} — `{{ event.actor.principal }}`{% endif %}"
                "{% if event.actor.source_ip %} from `{{ event.actor.source_ip }}`{% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %}"
                " on `{{ event.extra.tags.role }}`"
                "{% elif event.target.name %} on `{{ event.target.name }}`"
                "{% elif event.target.id %} on `{{ event.target.id }}`{% endif %}"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Single line, no fluff.",
            "template": (
                "{{ event.extra.message or event.action }}"
                "{% if event.actor.principal %} · {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} ({{ event.actor.source_ip }}){% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %} · {{ event.extra.tags.role }}{% endif %}"
            ),
        },
    ],
    "teams": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain English, fits Teams card formatting.",
            "template": (
                "**{{ event.extra.message or event.action }}**"
                "{% if event.actor.principal %} — `{{ event.actor.principal }}`{% endif %}"
                "{% if event.actor.source_ip %} from `{{ event.actor.source_ip }}`{% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %}"
                " on `{{ event.extra.tags.role }}`"
                "{% elif event.target.name %} on `{{ event.target.name }}`"
                "{% elif event.target.id %} on `{{ event.target.id }}`{% endif %}"
                "{% if event.severity %} _(severity: {{ event.severity }})_{% endif %}"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Single line.",
            "template": (
                "{{ event.extra.message or event.action }}"
                "{% if event.actor.principal %} · {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} ({{ event.actor.source_ip }}){% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %} · {{ event.extra.tags.role }}{% endif %}"
            ),
        },
    ],
    "email": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Human-readable summary at the top, full detail below.",
            "template": (
                "{{ event.extra.message or event.action }}"
                "{% if event.actor.principal %} — {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} from {{ event.actor.source_ip }}{% endif %}\n"
                "\n"
                "When:     {{ event.event_time }}\n"
                "Target:   {{ event.target.name or event.target.id or '-' }}\n"
                "{% if event.extra.tags %}Tags:     "
                "{% for k, v in event.extra.tags.items() %}{{ k }}={{ v }}{% if not loop.last %}, {% endif %}{% endfor %}\n{% endif %}"
                "Severity: {{ event.severity or 'unscored' }}\n"
                "Module:   {{ event.source.module }}\n"
                "Action:   {{ event.action }}\n"
                "Rules:    {{ event.rule_matches|join(', ') or '-' }}\n"
            ),
        },
        {
            "id": "detailed",
            "name": "Detailed (all fields)",
            "blurb": "Every field of the event in a labeled list.",
            "template": (
                "Action:   {{ event.action }}\n"
                "Severity: {{ event.severity or 'unscored' }}\n"
                "Time:     {{ event.event_time }}\n"
                "Actor:    {{ event.actor.principal or '-' }}"
                "{% if event.actor.source_ip %} (from {{ event.actor.source_ip }}){% endif %}\n"
                "Target:   {{ event.target.id or event.target.name or '-' }}\n"
                "Outcome:  {{ event.outcome }}\n"
                "Category: {{ event.category }}\n"
                "Module:   {{ event.source.module }}\n"
                "Rules:    {{ event.rule_matches|join(', ') or '-' }}\n"
            ),
        },
    ],
    "pagerduty": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Short title PagerDuty shows in the incident list.",
            "template": (
                "{{ event.action }} — {{ event.actor.principal or 'unknown' }}"
                "{% if event.actor.source_ip %} from {{ event.actor.source_ip }}{% endif %}"
            ),
        },
    ],
    "webhook": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain-English summary — full event JSON also sent in the body.",
            "template": (
                "{{ event.action }} — {{ event.actor.principal or 'unknown' }}"
                "{% if event.actor.source_ip %} from {{ event.actor.source_ip }}{% endif %}"
            ),
        },
    ],
}


# Channel.send() reads from this — defaults stay sensible if a saved channel
# has no message_template (None) and the user never picked a preset.
_DEFAULT_TEMPLATES: dict[str, str] = {
    ch_type: presets[0]["template"]
    for ch_type, presets in TEMPLATE_PRESETS.items()
}

# CRITICAL/HIGH/MEDIUM/LOW -> PagerDuty severity
_PD_SEVERITY = {
    "critical": "critical", "high": "error",
    "medium": "warning", "low": "info", "informational": "info",
}

_jinja = Environment(autoescape=False, undefined=StrictUndefined, trim_blocks=True)


def _env(var: str) -> str | None:
    """Read a secret from an env var; returns None if missing/empty."""
    return os.environ.get(var) or None


def _render(channel: Channel, event: Event) -> str:
    tpl_src = channel.message_template or _DEFAULT_TEMPLATES.get(channel.type, "")
    try:
        return _jinja.from_string(tpl_src).render(event=event.model_dump(mode="json"),
                                                  channel_name=channel.name)
    except Exception as exc:
        # Templates should never break delivery — fall back to a minimal text.
        return f"[{event.severity or 'unscored'}] {event.action} (template error: {exc})"


def summarize(event: Event) -> str:
    """Used by tests and the per-channel test-send helper."""
    return _render(Channel(name="_summary", type="slack", url=""), event)


# ---- HTTP helper -------------------------------------------------------------

def _post_json(url: str, payload: dict, timeout: int = _TIMEOUT) -> tuple[bool, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)


# ---- Per-type senders --------------------------------------------------------

def _send_slack(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    return _post_json(url, {"text": body})


def _send_webhook(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    return _post_json(url, {"summary": body, "event": event.model_dump(mode="json")})


def _send_teams(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    payload = {
        "@type": "MessageCard", "@context": "https://schema.org/extensions",
        "summary": f"BlackWatch: {event.action}",
        "title": f"BlackWatch [{event.severity.value if event.severity else 'unscored'}]",
        "text": body,
    }
    return _post_json(url, payload)


def _send_discord(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    return _post_json(url, {"content": body[:1990]})  # Discord has a 2000-char limit


def _send_pagerduty(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    key_env = cfg.get("routing_key_env")
    routing_key = _env(key_env) if key_env else cfg.get("routing_key")
    if not routing_key:
        return False, f"missing PagerDuty routing key (env {key_env} unset?)"
    sev = (event.severity.value if event.severity else "informational")
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": event.dedup_fingerprint,
        "payload": {
            "summary": body[:1024],
            "severity": _PD_SEVERITY.get(sev, "info"),
            "source": event.target.id or event.source.module or "blackwatch",
            "component": event.source.module,
            "class": event.category.value if event.category else "other",
            "custom_details": event.model_dump(mode="json"),
        },
    }
    return _post_json("https://events.pagerduty.com/v2/enqueue", payload)


def _send_email(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port", 587))
    from_addr = cfg.get("from_addr")
    to_addrs = cfg.get("to_addrs") or []
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    if not (host and from_addr and to_addrs):
        return False, "missing smtp_host / from_addr / to_addrs"
    pw_env = cfg.get("password_env")
    password = _env(pw_env) if pw_env else cfg.get("password")
    use_tls = bool(cfg.get("use_tls", True))
    sev = event.severity.value if event.severity else "unscored"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[BlackWatch][{sev}] {event.action}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    try:
        with smtplib.SMTP(host, port, timeout=_TIMEOUT) as s:
            if use_tls:
                s.starttls()
            if cfg.get("smtp_user") and password:
                s.login(cfg["smtp_user"], password)
            s.sendmail(from_addr, to_addrs, msg.as_string())
        return True, f"SMTP delivered to {len(to_addrs)} recipient(s)"
    except Exception as exc:
        return False, str(exc)


_SENDERS = {
    "slack": _send_slack,
    "webhook": _send_webhook,
    "teams": _send_teams,
    "discord": _send_discord,
    "pagerduty": _send_pagerduty,
    "email": _send_email,
}


def send(channel: Channel, event: Event) -> tuple[bool, str]:
    """Render the channel's template and dispatch via the type's sender."""
    sender = _SENDERS.get(channel.type)
    if sender is None:
        return False, f"unknown channel type: {channel.type}"
    body = _render(channel, event)
    return sender(channel.resolved_config(), body, event)
