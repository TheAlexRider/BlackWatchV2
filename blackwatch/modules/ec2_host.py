"""EC2 host agent adapter.

Consumes the JSON report the on-host reporter (scripts/ec2_agent.py) pushes to
SQS:

    {
      "kind": "ec2_report",
      "host": {"instance_id": "...", "hostname": "...", "account": "...", "region": "..."},
      "agent_version": "0.1",
      "uptime_seconds": 12345,
      "auth_events": ["<journalctl --output=json line>", ...]   # sshd + sudo
    }

and emits:
  * host.service.health        — heartbeat (drives the host_status read-model)
  * host.auth.ssh.success/failure
  * host.sudo.exec/failure

Pure transform. State (last-seen, staleness) lives in blackwatch/hosts/."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor,
    Category,
    Event,
    Observable,
    Outcome,
    Source,
    Target,
    Transport,
)
from .base import Adapter, IngestContext

_IP = r"(\d{1,3}(?:\.\d{1,3}){3})"
_SSH_OK = re.compile(rf"Accepted (\S+) for (\S+) from {_IP}")
_SSH_FAIL = re.compile(rf"Failed (\S+) for (?:invalid user )?(\S+) from {_IP}")
_SSH_INVALID = re.compile(rf"Invalid user (\S+) from {_IP}")
_SUDO_OK = re.compile(r"sudo:\s+(\S+)\s+:.*COMMAND=(.+)$")
_SUDO_USER = re.compile(r"sudo:\s+(\S+)\s+:")
_SUDO_FAIL_MARKERS = ("authentication failure", "NOT in the sudoers", "command not allowed",
                      "incorrect password attempt")

# Hard cap on the snapshots dict — a misbehaving / malicious agent shouldn't
# be able to make BlackWatch persist arbitrarily large JSONB rows. Beyond
# this we keep the heartbeat (so /hosts still shows the box) but drop
# snapshots, recording the size so it shows up in /events under
# extra.adapter_truncated.
_SNAPSHOT_BYTE_CAP = 512 * 1024

# instance_id must look like an EC2 identifier: i-XXXX (16 hex). Reject
# anything else so a compromised box can't push events under arbitrary
# instance_ids. If the agent runs on something that's not an EC2 (an
# Lightsail instance, a Mac in dev) we accept the hostname as a fallback;
# the adapter still won't crash, but rule writers can pin to the regex
# form for production data.
_INSTANCE_ID_RE = re.compile(r"^(i-[0-9a-f]{8,17}|[A-Za-z0-9._-]{1,64})$")


def _journal_message(entry: dict[str, Any]) -> str:
    msg = entry.get("MESSAGE", "")
    if isinstance(msg, list):
        try:
            return bytes(msg).decode("utf-8", "replace")
        except Exception:
            return ""
    return msg or ""


def _journal_time(entry: dict[str, Any]) -> datetime:
    ts = entry.get("__REALTIME_TIMESTAMP")
    try:
        return datetime.fromtimestamp(int(ts) / 1_000_000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


class Ec2HostAdapter(Adapter):
    module = "ec2.host"

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict) or raw.get("kind") != "ec2_report":
            return []

        # Defensive type checks. A malformed payload (corrupt SQS body, a
        # tampered agent on a compromised box, a future schema change) MUST
        # NOT crash the pipeline — just refuse the payload.
        host = raw.get("host")
        if not isinstance(host, dict):
            return []

        instance_id = host.get("instance_id") or "unknown"
        if not isinstance(instance_id, str) or not _INSTANCE_ID_RE.match(instance_id):
            return []  # reject obviously bogus IDs (incl. attempts to spoof)

        hostname = host.get("hostname") if isinstance(host.get("hostname"), str) else None
        account = (host.get("account") if isinstance(host.get("account"), str) else None) or ctx.account
        region = (host.get("region") if isinstance(host.get("region"), str) else None) or ctx.region

        def src() -> Source:
            return Source(module=self.module, vendor="aws", account=account, region=region,
                          transport=Transport.queue)

        def target() -> Target:
            return Target(id=instance_id, type="ec2.instance", name=hostname)

        events: list[Event] = []

        # Tags arrive on host{}; promote them to event extras so rules can
        # match on `extra.tags.env equals prod`, etc. (Tags ride on every
        # event the adapter emits below, not just the heartbeat — that's
        # what makes per-env routing work.)
        tags = host.get("tags") if isinstance(host, dict) else None
        tags_extra: dict[str, Any] = {"tags": tags} if isinstance(tags, dict) and tags else {}

        # 1) Heartbeat
        hb_extra: dict[str, Any] = {
            "instance_id": instance_id,
            "hostname": hostname,
            "uptime_seconds": raw.get("uptime_seconds"),
            "agent_version": raw.get("agent_version"),
            **tags_extra,
        }
        if raw.get("tick_duration_ms") is not None:
            hb_extra["tick_duration_ms"] = raw["tick_duration_ms"]
        if raw.get("collector_errors"):
            hb_extra["collector_errors"] = raw["collector_errors"]
        # v1.1 fields — always passed through. Projection compares each tick to
        # its previous state (or rolling baseline for CPU) to decide transitions.
        for k in ("memory", "cpu", "active_sessions", "rpm_db_corrupted"):
            if raw.get(k) is not None:
                hb_extra[k] = raw[k]
        # Always present (even empty) so projection can detect set-difference.
        hb_extra["stalled_collectors"] = raw.get("stalled_collectors") or []
        events.append(
            Event(
                source=src(),
                event_time=datetime.now(timezone.utc),
                category=Category.host,
                action="host.service.health",
                outcome=Outcome.success,
                target=target(),
                extra=hb_extra,
                raw={"kind": "ec2_report", "host": host},
            )
        )

        # 1b) State snapshot (only when the agent ships it — i.e. on change /
        # hourly resync). Projection diffs it vs. the last stored snapshot.
        # We size-cap defensively: a malicious or buggy agent shipping a
        # 50 MB snapshot would otherwise sit in JSONB forever and slow every
        # query. Over the cap → drop the body, record what happened, keep
        # the heartbeat above intact.
        snapshots = raw.get("snapshots")
        if isinstance(snapshots, dict):
            try:
                snap_bytes = len(json.dumps(snapshots).encode("utf-8"))
            except (TypeError, ValueError):
                snap_bytes = -1
            if 0 < snap_bytes <= _SNAPSHOT_BYTE_CAP:
                events.append(
                    Event(
                        source=src(),
                        event_time=datetime.now(timezone.utc),
                        category=Category.host,
                        action="host.state.snapshot",
                        outcome=Outcome.success,
                        target=target(),
                        extra={"instance_id": instance_id, "snapshots": snapshots, **tags_extra},
                        raw={"kind": "ec2_report", "host": host, "snapshots_present": True},
                    )
                )
            else:
                # Record the truncation as an event so /events shows the
                # operator that something's off, instead of just silently
                # dropping data.
                events.append(
                    Event(
                        source=src(),
                        event_time=datetime.now(timezone.utc),
                        category=Category.host,
                        action="host.state.snapshot.rejected",
                        outcome=Outcome.failure,
                        target=target(),
                        extra={
                            "instance_id": instance_id,
                            "reason": "snapshot_too_large" if snap_bytes > 0 else "snapshot_unserializable",
                            "size_bytes": snap_bytes,
                            "cap_bytes": _SNAPSHOT_BYTE_CAP,
                            **tags_extra,
                        },
                        raw={"kind": "ec2_report", "host": host, "snapshots_dropped": True},
                    )
                )

        # 1c) OOM-kill events from the kernel ring buffer. Deterministic event_id
        # from journal __CURSOR so re-reads of overlapping windows don't duplicate.
        for oom in raw.get("oom_events") or []:
            if not isinstance(oom, dict):
                continue
            cursor = oom.get("cursor") or f"{oom.get('ts','')}{oom.get('message','')}"
            try:
                event_time = datetime.fromtimestamp(int(oom["ts"]) / 1_000_000, tz=timezone.utc)
            except (KeyError, TypeError, ValueError):
                event_time = datetime.now(timezone.utc)
            events.append(
                Event(
                    event_id=str(uuid.uuid5(uuid.NAMESPACE_URL,
                                             f"host-oom:{instance_id}:{cursor}")),
                    source=src(),
                    event_time=event_time,
                    category=Category.host,
                    action="host.oom_kill",
                    outcome=Outcome.failure,
                    target=target(),
                    extra={
                        "instance_id": instance_id,
                        "kernel_message": oom.get("message"),
                        **tags_extra,
                    },
                    raw={"kind": "ec2_report.oom", "oom": oom},
                )
            )

        # 2) Auth events (journald sshd + sudo lines)
        for line in raw.get("auth_events") or []:
            entry = line if isinstance(line, dict) else _load(line)
            if entry is None:
                continue
            parsed = self._classify(_journal_message(entry))
            if parsed is None:
                continue
            action, outcome, user, ip, extra = parsed
            cursor = entry.get("__CURSOR") or f"{entry.get('__REALTIME_TIMESTAMP','')}{_journal_message(entry)}"
            observables = []
            if ip:
                observables.append(Observable(type="ip", value=ip))
            if user:
                observables.append(Observable(type="user", value=user))
            events.append(
                Event(
                    event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"host-auth:{instance_id}:{cursor}")),
                    source=src(),
                    event_time=_journal_time(entry),
                    category=Category.host,
                    action=action,
                    outcome=outcome,
                    actor=Actor(principal=user, source_ip=ip),
                    target=target(),
                    observables=observables,
                    extra={"instance_id": instance_id, **extra, **tags_extra},
                    raw=entry,
                )
            )
        return events

    @staticmethod
    def _classify(msg: str):
        """-> (action, outcome, user, ip, extra) or None."""
        m = _SSH_OK.search(msg)
        if m:
            method = m.group(1)
            # Password-based SSH success is a higher-signal event than key-based
            # (most boxes should have PasswordAuthentication off). Split it onto
            # its own action so rules and the UI can flag it distinctly.
            # keyboard-interactive often wraps PAM password underneath, so treat
            # it the same way.
            action = (
                "host.auth.ssh.password.success"
                if method in ("password", "keyboard-interactive")
                else "host.auth.ssh.success"
            )
            return action, Outcome.success, m.group(2), m.group(3), {"method": method}
        m = _SSH_FAIL.search(msg)
        if m:
            return "host.auth.ssh.failure", Outcome.failure, m.group(2), m.group(3), {"method": m.group(1)}
        m = _SSH_INVALID.search(msg)
        if m:
            return "host.auth.ssh.failure", Outcome.failure, m.group(1), m.group(2), {"reason": "invalid_user"}
        if "sudo:" in msg:
            m = _SUDO_OK.search(msg)
            if m:
                return "host.sudo.exec", Outcome.success, m.group(1), None, {"command": m.group(2).strip()}
            if any(marker in msg for marker in _SUDO_FAIL_MARKERS):
                um = _SUDO_USER.search(msg)
                return "host.sudo.failure", Outcome.failure, (um.group(1) if um else None), None, {}
        return None


def _load(line: str):
    try:
        return json.loads(line)
    except (ValueError, TypeError):
        return None
