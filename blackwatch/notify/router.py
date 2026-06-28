"""Notification routing (Phase 2).

Both rules and channels live in the DB and are managed from the UI. Matching
reuses the rule-engine `Condition`. Dispatch is asynchronous: matched (rule,
channel, event) tuples are ENQUEUED to the send-queue worker, which handles
rate-limit / digest / send / retry / log. The pipeline never blocks on a slow
channel.

On first boot, if the relevant DB tables are empty AND `notifications.yaml`
has a corresponding section, we seed once (legacy routes -> notification_rules,
legacy channels -> notification_channels). After that, the YAML is ignored;
the UI is canonical."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import storage
from ..event import Event, Severity, Source, _SEVERITY_ORDER
from ..rules.engine import eval_condition
from . import channels as channels_module
from . import worker as notify_worker
from .model import Channel, NotificationRule, NotifyConfig, Route


# ---- Legacy Route helpers (kept for migration + tests) ----------------------

def route_matches(route: Route, event: Event) -> bool:
    if not route.enabled:
        return False
    if route.min_severity is not None:
        from ..event import severity_rank
        if severity_rank(event.severity) < severity_rank(route.min_severity):
            return False
    if route.severity is not None and event.severity not in route.severity:
        return False
    if route.categories is not None and event.category.value not in route.categories:
        return False
    if route.modules is not None and event.source.module not in route.modules:
        return False
    if route.actions is not None and event.action not in route.actions:
        return False
    if route.tags is not None and not (set(route.tags) & set(event.tags)):
        return False
    return True


def route_to_condition(route: Route) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if route.min_severity is not None:
        idx = _SEVERITY_ORDER.index(route.min_severity.value)
        clauses.append({"field": "severity", "op": "in", "value": _SEVERITY_ORDER[idx:]})
    if route.severity is not None:
        clauses.append({"field": "severity", "op": "in",
                        "value": [s.value for s in route.severity]})
    if route.categories is not None:
        clauses.append({"field": "category", "op": "in", "value": route.categories})
    if route.modules is not None:
        clauses.append({"field": "source.module", "op": "in", "value": route.modules})
    if route.actions is not None:
        clauses.append({"field": "action", "op": "in", "value": route.actions})
    if route.tags is not None:
        clauses.append({"field": "tags", "op": "in", "value": route.tags})
    if not clauses:
        return {"field": "action", "op": "exists"}
    if len(clauses) == 1:
        return clauses[0]
    return {"all": clauses}


# ---- Notifier ---------------------------------------------------------------

def _row_to_channel(row: dict) -> Channel:
    return Channel(
        name=row["name"], type=row["type"], enabled=row["enabled"],
        config=row.get("config") or {}, message_template=row.get("message_template"),
        retries=row.get("retries", 3),
        retry_backoff_seconds=row.get("retry_backoff_seconds", 5),
        rate_limit_per_min=row.get("rate_limit_per_min", 0),
        dedup_window_seconds=row.get("dedup_window_seconds", 300),
        digest_window_seconds=row.get("digest_window_seconds", 0),
    )


class Notifier:
    """Loads channels + rules from the DB; dispatch enqueues to the worker."""

    def __init__(
        self,
        channels: dict[str, Channel] | None = None,
        rules: list[NotificationRule] | None = None,
        channel_ids: dict[str, str] | None = None,
    ) -> None:
        self.channels: dict[str, Channel] = channels or {}
        self.rules: list[NotificationRule] = rules or []
        self._channel_ids: dict[str, str] = channel_ids or {}
        # (rule_id, channel_name, fingerprint) -> last enqueue ts
        self._last_sent: dict[tuple[str, str, str], float] = {}

    def reload_rules(self) -> None:
        try:
            self.rules = [NotificationRule(**r) for r in storage.list_notification_rules()]
        except Exception:
            pass

    def reload_channels(self) -> None:
        try:
            rows = storage.list_notification_channels()
        except Exception:
            return
        self.channels = {r["name"]: _row_to_channel(r) for r in rows}
        self._channel_ids = {r["name"]: r["id"] for r in rows}

    def dispatch(self, event: Event) -> list[dict[str, Any]]:
        """Match rules, check ack/silence/throttle, ENQUEUE to worker.
        Returns per-(rule, channel) outcomes for the /ingest response."""
        results: list[dict[str, Any]] = []
        now_ts = time.time()
        now_dt = datetime.now(timezone.utc)

        # Per-fingerprint user ack: silence everything for this fingerprint
        try:
            if storage.is_fingerprint_acked(event.dedup_fingerprint):
                return [{"status": "acked", "fingerprint": event.dedup_fingerprint}]
        except Exception:
            pass

        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.silence_until and rule.silence_until > now_dt:
                continue
            try:
                if not eval_condition(rule.match, event):
                    continue
            except Exception:
                continue
            for cname in rule.channels:
                channel = self.channels.get(cname)
                if channel is None or not channel.enabled:
                    results.append({"rule": rule.name, "channel": cname, "status": "skipped"})
                    continue
                key = (rule.id, channel.name, event.dedup_fingerprint)
                window = rule.throttle_seconds or channel.dedup_window_seconds
                last = self._last_sent.get(key)
                if window > 0 and last is not None and now_ts - last < window:
                    results.append({"rule": rule.name, "channel": channel.name,
                                    "status": "throttled"})
                    continue
                self._last_sent[key] = now_ts
                notify_worker.get_worker().enqueue({
                    "rule": rule, "channel": channel,
                    "channel_id": self._channel_ids.get(cname),
                    "event": event,
                })
                results.append({"rule": rule.name, "channel": channel.name, "status": "queued"})
        return results

    def dispatch_direct(
        self,
        event: Event,
        channel_names: list[str],
        rule_name: str,
        rule_id: str | None = None,
        throttle_seconds: int = 0,
    ) -> list[dict[str, Any]]:
        """Bypass rule-matching and dispatch `event` to a specific list of
        channels. Used by features (perf alerts, future schedulers) that
        own their own rule semantics but still want to ride the existing
        channel/worker plumbing.

        Caller supplies a `rule_name` for logging/ack-tracking purposes;
        if `rule_id` is given, it's used as the rule-identity in the
        throttle key (so two perf rules pointing at the same channel for
        the same fingerprint don't share a throttle bucket).
        """
        results: list[dict[str, Any]] = []
        now_ts = time.time()

        # Honor the same ack semantics as the regular dispatch path.
        try:
            if storage.is_fingerprint_acked(event.dedup_fingerprint):
                return [{"status": "acked", "fingerprint": event.dedup_fingerprint}]
        except Exception:
            pass

        for cname in channel_names:
            channel = self.channels.get(cname)
            if channel is None or not channel.enabled:
                results.append({"rule": rule_name, "channel": cname, "status": "skipped"})
                continue
            key = (rule_id or rule_name, channel.name, event.dedup_fingerprint)
            window = throttle_seconds or channel.dedup_window_seconds
            last = self._last_sent.get(key)
            if window > 0 and last is not None and now_ts - last < window:
                results.append({"rule": rule_name, "channel": channel.name,
                                "status": "throttled"})
                continue
            self._last_sent[key] = now_ts
            # Build an ephemeral NotificationRule so the worker has the
            # shape it expects (it reads rule.name + rule.id for logging).
            # `match` is required by the model but we bypassed matching;
            # an empty Condition is the canonical "matches nothing" sentinel.
            from ..rules.model import Condition  # local import — avoids cycle
            virtual_rule = NotificationRule(
                id=rule_id or f"perf:{rule_name}",
                name=rule_name,
                enabled=True,
                match=Condition(),
                channels=[cname],
                throttle_seconds=throttle_seconds,
            )
            notify_worker.get_worker().enqueue({
                "rule": virtual_rule,
                "channel": channel,
                "channel_id": self._channel_ids.get(cname),
                "event": event,
            })
            results.append({"rule": rule_name, "channel": channel.name, "status": "queued"})
        return results

    def send_test(self, channel_name: str) -> dict[str, Any]:
        """Synchronous test send (bypasses the worker)."""
        channel = self.channels.get(channel_name)
        if channel is None:
            return {"channel": channel_name, "status": "unknown_channel"}
        test_event = Event(
            source=Source(module="blackwatch.test"),
            action="test.notification",
            severity=Severity.informational,
        )
        ok, detail = channels_module.send(channel, test_event)
        return {"channel": channel_name, "status": "sent" if ok else "error", "detail": detail}

    def test_rule(self, rule_id: str) -> list[dict[str, Any]]:
        rule = next((r for r in self.rules if r.id == rule_id), None)
        if rule is None:
            return [{"status": "unknown_rule"}]
        return [self.send_test(c) for c in rule.channels]


# ---- YAML seeding (one-time on first boot) ----------------------------------

def load_config(path: str | Path) -> NotifyConfig:
    file = Path(path)
    if not file.exists():
        return NotifyConfig()
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return NotifyConfig(**data)


def _seed_rules_from_yaml(cfg: NotifyConfig) -> None:
    try:
        if storage.list_notification_rules():
            return
    except Exception:
        return
    for route in cfg.routes:
        try:
            storage.upsert_notification_rule(
                rule_id=str(uuid.uuid4()), name=route.name, enabled=route.enabled,
                match=route_to_condition(route), channels=list(route.channels),
                throttle_seconds=0, priority=100,
            )
        except Exception:
            pass


def _seed_channels_from_yaml(cfg: NotifyConfig) -> None:
    try:
        if storage.list_notification_channels():
            return
    except Exception:
        return
    for ch in cfg.channels:
        try:
            storage.upsert_notification_channel(
                channel_id=str(uuid.uuid4()),
                name=ch.name, ctype=ch.type, enabled=ch.enabled,
                config=ch.resolved_config(),
                message_template=ch.message_template,
                retries=ch.retries, retry_backoff_seconds=ch.retry_backoff_seconds,
                rate_limit_per_min=ch.rate_limit_per_min,
                dedup_window_seconds=ch.dedup_window_seconds,
                digest_window_seconds=ch.digest_window_seconds,
            )
        except Exception:
            pass


_notifier: Notifier | None = None


def init_notifier(path: str | Path) -> None:
    global _notifier
    cfg = load_config(path)
    _seed_channels_from_yaml(cfg)
    _seed_rules_from_yaml(cfg)
    n = Notifier()
    n.reload_channels()
    n.reload_rules()
    _notifier = n


def get_notifier() -> Notifier:
    if _notifier is None:
        return Notifier()
    return _notifier
