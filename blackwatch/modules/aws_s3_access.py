"""S3 Server Access Log adapter.

Consumes payloads from the `aws_s3_access_pull` connector. Each payload is one
log file's worth of newline-delimited access log entries in AWS's
space-separated-with-quotes format:

    {
      "kind": "s3_access_log_batch",
      "log_bucket": "longhealth-security-s3-access-logs",
      "log_key":    "logs/prod-lh-textract/2026-08-09-14-05-33-XXXX",
      "source_bucket": "prod-lh-textract",  # parsed from key prefix
      "content":    "<raw log file text>"
    }

Emitted actions:

  * s3.object.access — one per parsed log line. Volume can be high; this
    action is registered in _PROJECTION_ONLY_ACTIONS on the pipeline so it
    feeds intel + UEBA hooks without cluttering the events table by default.
    Flip the pipeline entry if you need full storage for compliance evidence.

  * s3.object.access.anonymous — non-authenticated request (Requester = "-").
    On a fleet of PRIVATE buckets this should be zero — always alertable.

  * s3.object.access.error_burst — placeholder, not emitted here (would need a
    projection to track per-IP error counts). Left as a rule-side TODO.

Not extracted / deliberately dropped:
  * The full Request-URI (may contain patient identifiers or presigned tokens).
  * The Referer beyond a short prefix.
  * Object Key beyond the first path segment (contains PHI paths for some buckets).

For sensitive-bucket workflows that DO need per-object attribution, override
`_KEY_KEEP_FULL_FOR_BUCKETS` below (set of source-bucket names).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor, ActorType, Category, Event, Observable, ObservableType, Outcome,
    Source, Target, Transport,
)
from .base import Adapter, IngestContext

_MODULE = "aws.s3.access"

# Source buckets where the full object key is preserved on the event (needed
# for canary detection etc.). Everything else keeps only the top-level prefix
# to keep PHI out of the events table by default.
_KEY_KEEP_FULL_FOR_BUCKETS: set[str] = set()

# S3 access log fields are space-separated with quoted string fields and
# bracket-wrapped timestamp. This regex tokenizes one line into fields,
# handling the three shapes: bare token, [bracketed], "quoted".
_TOKEN_RE = re.compile(r'\[[^\]]*\]|"[^"]*"|\S+')


def _tokenize(line: str) -> list[str]:
    tokens = _TOKEN_RE.findall(line)
    # Strip enclosing brackets/quotes but preserve original content inside.
    cleaned: list[str] = []
    for t in tokens:
        if t.startswith("[") and t.endswith("]"):
            cleaned.append(t[1:-1])
        elif t.startswith('"') and t.endswith('"'):
            cleaned.append(t[1:-1])
        else:
            cleaned.append(t)
    return cleaned


# Positional field names for the current AWS S3 Server Access Log format.
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/LogFormat.html
# We don't require every field — future AWS versions may append more. Missing
# fields at the tail resolve to None.
_FIELDS = (
    "bucket_owner", "bucket", "time", "remote_ip", "requester", "request_id",
    "operation", "key", "request_uri", "http_status", "error_code",
    "bytes_sent", "object_size", "total_time_ms", "turnaround_time_ms",
    "referer", "user_agent", "version_id", "host_id", "sig_version",
    "cipher_suite", "auth_type", "host_header", "tls_version",
    "access_point_arn", "acl_required",
)


def _parse_line(line: str) -> dict[str, Any] | None:
    tokens = _tokenize(line)
    if len(tokens) < 8:  # too short to be a real access log line
        return None
    row: dict[str, Any] = {}
    for i, name in enumerate(_FIELDS):
        row[name] = tokens[i] if i < len(tokens) else None
    return row


def _parse_time(ts: str | None) -> datetime | None:
    """Access logs use `dd/Mon/YYYY:HH:MM:SS +ZZZZ`, e.g. `09/Aug/2026:14:05:33 +0000`."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%d/%b/%Y:%H:%M:%S %z").astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _int_or_none(v: Any) -> int | None:
    if v in (None, "-", ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _redact_key(source_bucket: str, key: str | None) -> str | None:
    """Keep the first path segment only, unless the bucket is on the keep-full
    list. `-` (no key) passes through unchanged."""
    if key in (None, "-", ""):
        return key
    if source_bucket in _KEY_KEEP_FULL_FOR_BUCKETS:
        return key
    # Trim to first segment (before first `/`). Anything below that is dropped.
    slash = key.find("/")
    return key if slash == -1 else key[:slash + 1] + "…"


class AwsS3AccessAdapter(Adapter):
    module = _MODULE

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict):
            return []
        content = raw.get("content")
        if not isinstance(content, str):
            return []
        log_key = raw.get("log_key") or "unknown"
        source_bucket = raw.get("source_bucket") or "unknown"
        log_bucket = raw.get("log_bucket") or "unknown"

        events: list[Event] = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            row = _parse_line(line)
            if row is None:
                continue

            requester = row.get("requester") or "-"
            source_ip = row.get("remote_ip")
            if source_ip in ("-", ""):
                source_ip = None
            operation = row.get("operation") or "UNKNOWN"
            key = _redact_key(source_bucket, row.get("key"))
            http_status = _int_or_none(row.get("http_status"))
            bytes_sent = _int_or_none(row.get("bytes_sent"))
            request_id = row.get("request_id") or ""
            event_time = _parse_time(row.get("time")) or datetime.now(timezone.utc)

            outcome: Outcome
            if http_status is None:
                outcome = Outcome.success
            elif http_status < 400:
                outcome = Outcome.success
            elif http_status in (401, 403):
                outcome = Outcome.failure
            else:
                outcome = Outcome.failure

            # Deterministic event_id: request_id is unique per S3 API call, so
            # reprocessing the same log file yields identical event_ids —
            # storage.insert_event dedupes via ON CONFLICT DO NOTHING.
            event_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"s3access:{source_bucket}:{request_id}:{line_no}",
            ))

            # Anonymous / unauthenticated request. Almost always a signal on a
            # private-bucket fleet — worth its own action so rules match cheaply.
            is_anon = requester in ("-", "", None)
            action = "s3.object.access.anonymous" if is_anon else "s3.object.access"

            observables: list[Observable] = []
            if source_ip:
                observables.append(Observable(type=ObservableType.ip, value=source_ip))

            extra: dict[str, Any] = {
                "operation": operation,
                "http_status": http_status,
                "bytes_sent": bytes_sent,
                "log_bucket": log_bucket,
                "log_key": log_key,
                "user_agent": row.get("user_agent"),
                "tls_version": row.get("tls_version"),
                "auth_type": row.get("auth_type"),
                "error_code": row.get("error_code") if row.get("error_code") not in ("-", "") else None,
            }
            # Drop None values so events stay small.
            extra = {k: v for k, v in extra.items() if v is not None}

            events.append(Event(
                event_id=event_id,
                event_time=event_time,
                source=Source(module=_MODULE, transport=Transport.poll, account=None, region=None),
                actor=Actor(
                    # Requester ARN identifies a user or role; anonymous
                    # requests have neither, so map to `unknown`.
                    type=ActorType.unknown if is_anon else ActorType.user,
                    principal=requester if not is_anon else None,
                    source_ip=source_ip,
                ),
                target=Target(type="s3_object", id=f"{source_bucket}/{key}" if key else source_bucket),
                category=Category.storage,
                action=action,
                outcome=outcome,
                observables=observables,
                extra=extra,
                raw={"module": _MODULE},
            ))
        return events
