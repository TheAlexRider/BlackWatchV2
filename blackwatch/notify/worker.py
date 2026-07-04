"""Send-queue worker (Phase 2). The Notifier enqueues matched (rule, channel,
event) tuples; this worker thread drains the queue, applies per-channel rate
limit + digest, calls channel.send() with retries, and records every attempt
in notification_log. Keeps the ingest path snappy by isolating slow / flaky
channels."""

from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from .. import storage
from ..event import Event, Severity, Source
from . import channels as channels_module
from .model import Channel

_TICK_SECONDS = 0.5  # how often the worker wakes to flush digests
_MAX_LOG_PREVIEW = 500


def _now_ts() -> float:
    return time.time()


def _preview(
    channel: Channel, event: Event, rule_template: str | None = None,
) -> str:
    try:
        body = channels_module._render(channel, event, rule_template=rule_template)
    except Exception as exc:
        body = f"(render error: {exc})"
    return body[:_MAX_LOG_PREVIEW]


def _log(entry: dict[str, Any]) -> None:
    try:
        storage.insert_notification_log(entry)
    except Exception:
        pass  # never let logging failure break delivery


def _record_channel_status(
    channel_id: str | None, status: str, error: str | None, sent_at: datetime | None
) -> None:
    if not channel_id:
        return
    try:
        storage.set_notification_channel_status(channel_id, status, error, sent_at)
    except Exception:
        pass


class _RateLimiter:
    """Per-channel sliding-window rate limit (N/min). 0 = unlimited."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, channel: Channel) -> bool:
        limit = channel.rate_limit_per_min or 0
        if limit <= 0:
            return True
        now = _now_ts()
        bucket = self._hits[channel.name]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


class _DigestBuffer:
    """Per-channel digest: buffer items; due() returns True once the first
    buffered item's age exceeds digest_window_seconds."""

    def __init__(self) -> None:
        self._buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._first_at: dict[str, float] = {}

    def add(self, channel_name: str, item: dict[str, Any]) -> None:
        if channel_name not in self._first_at:
            self._first_at[channel_name] = _now_ts()
        self._buffers[channel_name].append(item)

    def due(self, channel_name: str, window_seconds: int) -> bool:
        first = self._first_at.get(channel_name)
        if first is None or not self._buffers.get(channel_name):
            return False
        return (_now_ts() - first) >= window_seconds

    def drain(self, channel_name: str) -> list[dict[str, Any]]:
        items = self._buffers.pop(channel_name, [])
        self._first_at.pop(channel_name, None)
        return items

    def channel_names(self) -> list[str]:
        return list(self._buffers.keys())


class Worker:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ratelimit = _RateLimiter()
        self._digest = _DigestBuffer()

    # ---- public API ---------------------------------------------------------

    def enqueue(self, item: dict[str, Any]) -> None:
        """item = {rule, channel (Channel), channel_id, event}"""
        self._q.put(item)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="notify-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    # ---- main loop ----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._flush_digests_if_due()
            try:
                item = self._q.get(timeout=_TICK_SECONDS)
            except queue.Empty:
                continue
            try:
                self.handle_one(item)
            except Exception:
                pass  # never crash the worker

    # ---- per-item handling --------------------------------------------------

    def handle_one(self, item: dict[str, Any]) -> dict[str, Any]:
        """Process one queued item. Returns the log entry written.
        Public for tests — exercises rate-limit + digest + send + retry."""
        rule = item["rule"]
        channel: Channel = item["channel"]
        event: Event = item["event"]
        channel_id = item.get("channel_id")
        rule_tpl = getattr(rule, "message_template", None)

        log_skel = {
            "rule_id": getattr(rule, "id", None),
            "rule_name": getattr(rule, "name", None),
            "channel_id": channel_id, "channel_name": channel.name,
            "event_id": event.event_id, "event_action": event.action,
            "event_severity": event.severity.value if event.severity else None,
        }

        # Rate-limit before anything else
        if not self._ratelimit.allow(channel):
            entry = {**log_skel, "status": "rate_limited",
                     "body_preview": _preview(channel, event, rule_tpl)}
            _log(entry)
            return entry

        # Digest: buffer; the loop flushes when the window expires
        if channel.digest_window_seconds > 0:
            self._digest.add(channel.name, {"rule": rule, "event": event, "channel": channel,
                                            "channel_id": channel_id})
            entry = {**log_skel, "status": "digested",
                     "body_preview": _preview(channel, event, rule_tpl)}
            _log(entry)
            return entry

        return self._send_with_retry(channel, event, log_skel, rule_tpl)

    def _send_with_retry(
        self, channel: Channel, event: Event, log_skel: dict[str, Any],
        rule_tpl: str | None = None,
    ) -> dict[str, Any]:
        retries = max(0, channel.retries)
        backoff = max(1, channel.retry_backoff_seconds)
        last_err: str | None = None
        for attempt in range(retries + 1):
            ok, detail = channels_module.send(channel, event, rule_template=rule_tpl)
            if ok:
                _record_channel_status(log_skel["channel_id"], "ok", None,
                                       datetime.now(timezone.utc))
                entry = {**log_skel, "status": "sent", "retries_used": attempt,
                         "body_preview": _preview(channel, event, rule_tpl),
                         "error_message": None}
                _log(entry)
                return entry
            last_err = detail
            if attempt < retries:
                self._stop.wait(backoff * (2 ** attempt))
                if self._stop.is_set():
                    break
        _record_channel_status(log_skel["channel_id"], "error", last_err, None)
        entry = {**log_skel, "status": "failed", "retries_used": retries,
                 "body_preview": _preview(channel, event, rule_tpl),
                 "error_message": last_err}
        _log(entry)
        return entry

    # ---- digest flush -------------------------------------------------------

    def _flush_digests_if_due(self) -> None:
        for cname in self._digest.channel_names():
            items = self._digest._buffers.get(cname, [])
            if not items:
                continue
            channel: Channel = items[0]["channel"]
            if not self._digest.due(cname, channel.digest_window_seconds):
                continue
            self._flush_one(channel, self._digest.drain(cname))

    def _flush_one(self, channel: Channel, items: list[dict[str, Any]]) -> None:
        lines = []
        for it in items:
            ev: Event = it["event"]
            lines.append(f"- [{(ev.severity.value if ev.severity else '-'):>8}] "
                         f"{ev.action} by {ev.actor.principal or '-'}")
        body = (f"BlackWatch digest: {len(items)} events in the last "
                f"{channel.digest_window_seconds}s\n" + "\n".join(lines))

        # Synthetic event the channel-specific senders can receive uniformly.
        digest_event = Event(
            source=Source(module="blackwatch.digest"),
            action="notification.digest",
            severity=Severity.informational,
            extra={"items": len(items)},
        )

        # Bypass templating: call the type's sender with the prebuilt body.
        sender = channels_module._SENDERS.get(channel.type)
        if sender is None:
            return
        ok, detail = sender(channel.resolved_config(), body, digest_event)
        _log({
            "rule_name": "(digest)", "channel_name": channel.name,
            "event_action": "notification.digest",
            "status": "sent" if ok else "failed",
            "body_preview": body[:_MAX_LOG_PREVIEW],
            "error_message": None if ok else detail,
        })


_worker: Worker | None = None


def get_worker() -> Worker:
    global _worker
    if _worker is None:
        _worker = Worker()
    return _worker


def start() -> None:
    get_worker().start()


def stop() -> None:
    if _worker is not None:
        _worker.stop()
