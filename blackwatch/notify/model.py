"""Notification config model. Channels are defined once; routes map scored
events to channels. All of this lives in one file (notifications.yaml) so the
operator configures alerting in a single place, not across SNS/Chatbot/etc."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..event import Severity
from ..rules.model import Condition


ChannelType = Literal["slack", "webhook", "email", "pagerduty", "teams", "discord"]


class Channel(BaseModel):
    """Phase 2 channel — DB-backed when loaded via Notifier; the legacy YAML
    `channels:` list still uses this for the one-time seed."""

    name: str
    type: ChannelType
    enabled: bool = True
    # Type-specific config — URL for webhook/slack/teams/discord; SMTP details
    # for email; routing_key_env for pagerduty; etc. Secrets are NEVER stored
    # here — config holds the *name* of the env var (e.g. password_env).
    config: dict = Field(default_factory=dict)
    # Legacy `url` field — supported for YAML seed back-compat (mapped into config).
    url: str | None = None
    message_template: str | None = None  # None -> use per-type default
    retries: int = 3
    retry_backoff_seconds: int = 5
    rate_limit_per_min: int = 0  # 0 = unlimited
    dedup_window_seconds: int = 300
    digest_window_seconds: int = 0  # 0 = off

    def resolved_config(self) -> dict:
        """Map legacy `url` into `config['url']` for back-compat."""
        out = dict(self.config or {})
        if self.url and "url" not in out:
            out["url"] = self.url
        return out


class Route(BaseModel):
    """A route matches an event if every specified criterion matches (AND).
    Unspecified criteria are ignored. Routes are opt-in: an event only notifies
    if at least one route matches it."""

    name: str
    enabled: bool = True
    min_severity: Severity | None = None
    severity: list[Severity] | None = None
    categories: list[str] | None = None
    modules: list[str] | None = None
    actions: list[str] | None = None
    tags: list[str] | None = None
    channels: list[str] = Field(default_factory=list)


class NotifyConfig(BaseModel):
    channels: list[Channel] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)


class NotificationRule(BaseModel):
    """Phase 1 — DB-backed, UI-managed rule deciding whether an event should
    notify, and to which channel(s). `match` is a Condition tree (same model as
    detection rules), so the full operator vocabulary applies."""

    id: str
    name: str
    enabled: bool = True
    match: Condition
    channels: list[str] = Field(default_factory=list)
    # 0 = use the channel's dedup_window_seconds; non-zero overrides per rule.
    throttle_seconds: int = 0
    silence_until: datetime | None = None
    priority: int = 100
