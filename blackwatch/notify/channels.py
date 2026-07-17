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

from jinja2 import ChainableUndefined, Environment, StrictUndefined  # noqa: F401

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

# Severity emojis were removed from the default presets — operators can
# reintroduce them via the template picker if they want. The old friendly
# preset always prepended one which was not customisable and felt noisy.

TEMPLATE_PRESETS: dict[str, list[dict[str, str]]] = {
    "slack": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain English, easy to scan in a channel. "
                     "When an event provides its own formatted body (perf "
                     "alerts, FIM events), that body is used verbatim so its "
                     "own markdown/newlines are preserved.",
            "template": (
                # Two rendering modes:
                #   1. Event has extra.message → it's already formatted by the
                #      producer (perf_alerts.py, FIM). Pass it through
                #      unchanged so its own markdown/newlines aren't wrapped
                #      in another `*..*` (which garbled the headline as
                #      `**...*`).
                #   2. Plain event → wrap the action name in `*..*` and append
                #      the actor/target/severity trailer, matching the classic
                #      Slack event line.
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}*{{ event.action }}*"
                "{% if event.actor.principal %} — `{{ event.actor.principal }}`{% endif %}"
                "{% if event.actor.source_ip %} from `{{ event.actor.source_ip }}`{% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %}"
                " on `{{ event.extra.tags.role }}`"
                "{% elif event.target.name %} on `{{ event.target.name }}`"
                "{% elif event.target.id %} on `{{ event.target.id }}`{% endif %}"
                "{% if event.severity %} _(severity: {{ event.severity }})_{% endif %}"
                "{% endif %}"
            ),
        },
        {
            "id": "detailed",
            "name": "Detailed",
            "blurb": "Multi-line with all key fields. Producer-formatted "
                     "bodies (perf, FIM, ECS) pass through verbatim so their "
                     "own layout isn't double-wrapped.",
            "template": (
                # Same two-mode split as Friendly: if the producer already
                # formatted a message (perf/FIM/ECS all set extra.message
                # today), render it verbatim. Otherwise build the classic
                # multi-line event card with actor/target/tags/severity rows.
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}*{{ event.action }}*\n"
                "{% if event.actor.principal %}• *Who:* {{ event.actor.principal }}\n{% endif %}"
                "{% if event.actor.source_ip %}• *From:* {{ event.actor.source_ip }}\n{% endif %}"
                "• *When:* {{ event.event_time }}\n"
                "• *Target:* {{ event.target.name or event.target.id or '—' }}\n"
                "{% if event.extra.tags %}• *Tags:* "
                "{% for k, v in event.extra.tags.items() %}{{ k }}={{ v }}{% if not loop.last %}, {% endif %}{% endfor %}\n{% endif %}"
                "{% if event.severity %}• *Severity:* {{ event.severity }}\n{% endif %}"
                "{% if event.rule_matches %}• *Matched rules:* {{ event.rule_matches|join(', ') }}{% endif %}"
                "{% endif %}"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Single line, no fluff. Best for a noisy logs channel. "
                     "Producer-formatted bodies pass through verbatim so "
                     "actor/tag suffixes aren't double-appended.",
            "template": (
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}{{ event.action }}"
                "{% if event.actor.principal %} · {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} ({{ event.actor.source_ip }}){% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %} · {{ event.extra.tags.role }}{% endif %}"
                "{% endif %}"
            ),
        },
    ],
    "discord": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain English. Uses extra.message verbatim when the "
                     "producer supplied one (perf, FIM); otherwise formats a "
                     "plain-event line.",
            "template": (
                # Same two-mode logic as Slack — see that preset's comment.
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}**{{ event.action }}**"
                "{% if event.actor.principal %} — `{{ event.actor.principal }}`{% endif %}"
                "{% if event.actor.source_ip %} from `{{ event.actor.source_ip }}`{% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %}"
                " on `{{ event.extra.tags.role }}`"
                "{% elif event.target.name %} on `{{ event.target.name }}`"
                "{% elif event.target.id %} on `{{ event.target.id }}`{% endif %}"
                "{% endif %}"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Single line, no fluff. Producer-formatted bodies pass "
                     "through verbatim.",
            "template": (
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}{{ event.action }}"
                "{% if event.actor.principal %} · {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} ({{ event.actor.source_ip }}){% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %} · {{ event.extra.tags.role }}{% endif %}"
                "{% endif %}"
            ),
        },
    ],
    "teams": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain English, fits Teams card formatting. Passes "
                     "already-formatted producer messages through verbatim.",
            "template": (
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}**{{ event.action }}**"
                "{% if event.actor.principal %} — `{{ event.actor.principal }}`{% endif %}"
                "{% if event.actor.source_ip %} from `{{ event.actor.source_ip }}`{% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %}"
                " on `{{ event.extra.tags.role }}`"
                "{% elif event.target.name %} on `{{ event.target.name }}`"
                "{% elif event.target.id %} on `{{ event.target.id }}`{% endif %}"
                "{% if event.severity %} _(severity: {{ event.severity }})_{% endif %}"
                "{% endif %}"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Single line. Producer-formatted bodies pass through "
                     "verbatim.",
            "template": (
                "{% if event.extra.message %}{{ event.extra.message }}"
                "{% else %}{{ event.action }}"
                "{% if event.actor.principal %} · {{ event.actor.principal }}{% endif %}"
                "{% if event.actor.source_ip %} ({{ event.actor.source_ip }}){% endif %}"
                "{% if event.extra.tags and event.extra.tags.role %} · {{ event.extra.tags.role }}{% endif %}"
                "{% endif %}"
            ),
        },
    ],
    "email": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Human-readable summary at the top, full detail below. "
                     "Producer-formatted bodies replace the whole summary.",
            "template": (
                "{% if event.extra.message %}{{ event.extra.message }}\n"
                "{% else %}{{ event.action }}"
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
                "{% endif %}"
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


# ---- Perf-alert template presets --------------------------------------------
#
# Perf-alert rules use a FLAT context (hostname, metric_label, threshold, …)
# instead of the event.* shape. Presets here reference those flat vars so
# the operator gets ready-to-use starter templates. The picker in the perf
# wizard fetches these via ?context_kind=perf.
PERF_TEMPLATE_PRESETS: dict[str, list[dict[str, str]]] = {
    "slack": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "One line: what fired, on which host, at what value.",
            "template": (
                "*{{ metric_label }} at "
                "{{ '%.1f' | format(current_value) }}%* on `{{ hostname }}`"
                " _(threshold {{ threshold }}%, {{ window_minutes }}m)_"
            ),
        },
        {
            "id": "detailed",
            "name": "Detailed",
            "blurb": "Multi-line — metric, host, value, tags. Headline shows the "
                     "specific host that breached (not the rule name), so a "
                     "fleet-wide rule still points at the culprit.",
            "template": (
                "*{{ metric_label }} on {{ hostname }}*\n"
                "• *Value:* {{ '%.1f' | format(current_value) }}% "
                "(threshold {{ threshold }}%)\n"
                "• *Window:* {{ window_minutes }} minutes\n"
                "• *Rule:* {{ rule_name }}"
                "{% if tags.env %}\n• *Env:* {{ tags.env }}{% endif %}"
                "{% if tags.role %}\n• *Role:* {{ tags.role }}{% endif %}"
            ),
        },
        {
            "id": "rich",
            "name": "Rich (distinct)",
            "blurb": "Bigger headline, unicode divider, observation window + "
                     "fired-at footer. Pairs with the severity-coloured "
                     "attachment stripe so the alert pops in a busy channel.",
            "template": (
                "*{{ metric_label }} · {{ hostname }}*  "
                "`{{ '%.1f' | format(current_value) }}%`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "• *Threshold:* {{ threshold }}% for {{ window_minutes }}m\n"
                "• *Window:* {{ window_range }}\n"
                "{% if tags.env %}• *Env:* {{ tags.env }}"
                "{% if tags.role %} · {{ tags.role }}{% endif %}\n{% endif %}"
                "_Fired {{ fired_at }} · {{ rule_name }}_"
            ),
        },
        {
            "id": "compact",
            "name": "Compact (one line)",
            "blurb": "Terse. For a noisy metrics channel.",
            "template": (
                "{{ metric_label }} {{ '%.1f' | format(current_value) }}% "
                "on {{ hostname }} (thr {{ threshold }}%)"
            ),
        },
    ],
    "discord": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "One line.",
            "template": (
                "**{{ metric_label }} at "
                "{{ '%.1f' | format(current_value) }}%** on `{{ hostname }}`"
                " _(threshold {{ threshold }}%, {{ window_minutes }}m)_"
            ),
        },
        {
            "id": "compact",
            "name": "Compact",
            "blurb": "Single line.",
            "template": (
                "{{ metric_label }} {{ '%.1f' | format(current_value) }}% "
                "on {{ hostname }} (thr {{ threshold }}%)"
            ),
        },
    ],
    "teams": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Fits Teams card formatting.",
            "template": (
                "**{{ metric_label }} at {{ '%.1f' | format(current_value) }}%**"
                " on `{{ hostname }}`"
                " _(threshold {{ threshold }}%, {{ window_minutes }}m)_"
            ),
        },
    ],
    "email": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Summary + rule detail.",
            "template": (
                "{{ metric_label }} at {{ '%.1f' | format(current_value) }}% "
                "on {{ hostname }}\n"
                "\n"
                "Rule:      {{ rule_name }}\n"
                "Threshold: {{ threshold }}%\n"
                "Window:    {{ window_minutes }} minutes\n"
                "Severity:  {{ severity }}\n"
                "Host:      {{ hostname }} ({{ instance_id }})\n"
                "{% if tags %}Tags:      "
                "{% for k, v in tags.items() %}{{ k }}={{ v }}"
                "{% if not loop.last %}, {% endif %}{% endfor %}\n{% endif %}"
            ),
        },
    ],
    "pagerduty": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Short title for the incident list.",
            "template": (
                "{{ metric_label }} {{ '%.1f' | format(current_value) }}% "
                "on {{ hostname }} (thr {{ threshold }}%)"
            ),
        },
    ],
    "webhook": [
        {
            "id": "friendly",
            "name": "Friendly (recommended)",
            "blurb": "Plain-English summary.",
            "template": (
                "{{ metric_label }} {{ '%.1f' | format(current_value) }}% "
                "on {{ hostname }} (thr {{ threshold }}%)"
            ),
        },
    ],
}

# CRITICAL/HIGH/MEDIUM/LOW -> PagerDuty severity
_PD_SEVERITY = {
    "critical": "critical", "high": "error",
    "medium": "warning", "low": "info", "informational": "info",
}

# ChainableUndefined lets templates safely traverse optional paths like
# `event.extra.message` or `event.extra.tags.role` without raising when a
# key isn't present. Combined with `{{ X or fallback }}` and `{% if X %}`,
# missing fields cleanly degrade to the fallback path. StrictUndefined
# would have raised here — which is great for catching typos but bad for
# optional fields that vary across event types (perf vs auth vs FIM).
_jinja = Environment(autoescape=False, undefined=ChainableUndefined, trim_blocks=True)


def _env(var: str) -> str | None:
    """Read a secret from an env var; returns None if missing/empty."""
    return os.environ.get(var) or None


def _render(
    channel: Channel,
    event: Event,
    rule_template: str | None = None,
) -> str:
    """Render the outgoing message body. Priority: rule template > channel
    template > per-type default. Rule-level override lets one channel
    deliver differently-worded alerts depending on which rule matched
    (e.g. terse "🚨 CRITICAL" from the critical rule vs. an "FYI:" line
    from the medium rule, both to #ops-slack)."""
    tpl_src = (
        (rule_template or "").strip()
        or channel.message_template
        or _DEFAULT_TEMPLATES.get(channel.type, "")
    )
    try:
        return _jinja.from_string(tpl_src).render(
            event=event.model_dump(mode="json"),
            channel_name=channel.name,
        )
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

# Severity color palette — matches the UI's globals.css tokens so an alert
# in Slack/Discord/Teams reads the same colour as its row in the dashboard.
# Slack/Teams take "#RRGGBB"; Discord takes a decimal int.
_SEV_HEX: dict[str, str] = {
    "critical":      "#F43F5E",
    "high":          "#FB923C",
    "medium":        "#FACC15",
    "low":           "#60A5FA",
    "informational": "#8E8E93",
}


def _sev_str(event: Event) -> str:
    sev = event.severity
    if sev is None:
        return "informational"
    # `sev` may be an Enum or a raw string depending on how the event was
    # built. Accept both.
    v = getattr(sev, "value", sev)
    return str(v).lower()


def _sev_hex(event: Event) -> str:
    return _SEV_HEX.get(_sev_str(event), _SEV_HEX["informational"])


def _send_slack(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    """Deliver the rendered body as a Slack attachment with a severity-
    coloured left border. The border is what makes an alert visually
    distinct in a channel — same convention as CloudWatch/Datadog/PagerDuty.
    Falls back to a plain-text message if the attachment API misbehaves."""
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    sev = _sev_str(event)
    # Attachment layout:
    #   • color   → the vertical stripe on the left
    #   • text    → the rendered template body (markdown enabled)
    #   • footer  → "BlackWatch · <severity>" so a channel with mixed sources
    #               still tells the reader who sent it
    #   • ts      → epoch seconds; Slack renders it as "1 min ago" beside footer
    ts = None
    try:
        et = event.event_time
        if et is not None:
            ts = int(et.timestamp())
    except Exception:
        ts = None
    attachment: dict[str, Any] = {
        "color": _sev_hex(event),
        "text": body,
        "mrkdwn_in": ["text"],
        "footer": f"BlackWatch · {sev}",
    }
    if ts is not None:
        attachment["ts"] = ts
    return _post_json(url, {"attachments": [attachment]})


def _send_webhook(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    return _post_json(url, {"summary": body, "event": event.model_dump(mode="json")})


def _send_teams(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    """Legacy MessageCard with a themeColor stripe. `themeColor` shows up as
    the coloured bar down the left of the Teams card — same visual anchor as
    the Slack attachment stripe."""
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    sev = _sev_str(event)
    # themeColor is a 6-char hex, NO "#" prefix (Teams quirk).
    theme_color = _sev_hex(event).lstrip("#")
    payload = {
        "@type": "MessageCard", "@context": "https://schema.org/extensions",
        "summary": f"BlackWatch: {event.action}",
        "themeColor": theme_color,
        "title": f"BlackWatch · {sev}",
        "text": body,
    }
    return _post_json(url, payload)


def _send_discord(cfg: dict, body: str, event: Event) -> tuple[bool, str]:
    """Discord embed with a severity-coloured left border. Discord's
    `color` is a decimal int (0xRRGGBB), unlike Slack's hex string."""
    url = cfg.get("url")
    if not url:
        return False, "missing config.url"
    # Discord embed description is capped at 4096; well above our render size,
    # but truncate defensively so we never lose the tail of a big alert.
    description = body if len(body) <= 4000 else (body[:3990] + "…")
    hex_str = _sev_hex(event).lstrip("#")
    try:
        color_int = int(hex_str, 16)
    except ValueError:
        color_int = 0x8E8E93
    embed: dict[str, Any] = {
        "description": description,
        "color": color_int,
        "footer": {"text": f"BlackWatch · {_sev_str(event)}"},
    }
    try:
        et = event.event_time
        if et is not None:
            embed["timestamp"] = et.isoformat()
    except Exception:
        pass
    return _post_json(url, {"embeds": [embed]})


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


def send(
    channel: Channel,
    event: Event,
    rule_template: str | None = None,
) -> tuple[bool, str]:
    """Render the message body and dispatch via the type's sender.
    If rule_template is set, it wins over the channel's default."""
    sender = _SENDERS.get(channel.type)
    if sender is None:
        return False, f"unknown channel type: {channel.type}"
    body = _render(channel, event, rule_template=rule_template)
    return sender(channel.resolved_config(), body, event)
