"""AWS API Gateway v2 (HTTP API) adapter.

Consumes payloads from the BW forwarder Lambda, which is subscribed to each
API Gateway stage's access log group. Envelope shape from the Lambda:

    {
      "kind": "api_gw_log_batch",
      "log_group": "/aws/gateway/<api-name>",
      "log_stream": "<stream-name>",
      "api_name":  "<api-name>",
      "owner":     "<account-id>",
      "events":    [ {"ts": <ms>, "message": "<json-line>"} ]
    }

Each event's `message` is one JSON line matching the access-log format
configured on the stage. See docs/api-gateway.md for the exact field list.

We deliberately DO NOT ingest `path` or any identity headers here — those
are PHI-adjacent under HIPAA (URL contains patient UUIDs; headers carry
physician/patient UUIDs). Detection at the API Gateway layer is limited
to source IP, method, routeKey (always the coarse proxy template on this
API), status, latency, response size, and user agent. Richer per-endpoint
/ per-identity detection lives in the app-layer audit log, which is
already HIPAA-scoped.

Emitted actions:

  * api.request         — every request (PROJECTION_ONLY — not stored)
  * api.auth.failure    — HTTP 401 or 403
  * api.error           — HTTP 5xx
  * api.scanner_ua      — user-agent matches a known scanner signature
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..event import (
    Actor, Category, Event, Observable, Outcome, Source, Target, Transport,
)
from .base import Adapter, IngestContext

_MODULE = "aws.api_gw"

# Known scanner / bot signatures. Substring match on the User-Agent header
# (lowercased). Extend as new tools show up; keep conservative — false
# positives on "curl" or "python-requests" would drown the operator.
_SCANNER_UA_PATTERNS = (
    "sqlmap",
    "nikto",
    "dirbuster",
    "nuclei",
    "wpscan",
    "acunetix",
    "netsparker",
    "burpsuite",
    "burp collaborator",
    "masscan",
    "zgrab",
    "nmap scripting engine",
    "openvas",
    "arachni",
    "havij",
    "gobuster",
    "ffuf",
    "feroxbuster",
    "wfuzz",
)


class AwsApiGwAdapter(Adapter):
    module = _MODULE

    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        if not isinstance(raw, dict):
            return []
        events_in = raw.get("events") or []
        if not events_in:
            return []
        api_name = raw.get("api_name") or "unknown"

        try:
            transport = Transport(ctx.transport)
        except ValueError:
            transport = Transport.queue

        out: list[Event] = []
        for entry in events_in:
            message = entry.get("message") if isinstance(entry, dict) else None
            if not message:
                continue
            parsed = _parse_json_line(message)
            if parsed is None:
                continue
            ts = _parse_ts(entry.get("ts"), parsed.get("requestTimeEpoch"))

            derived = _derive_events(parsed, api_name, ts, transport)
            out.extend(derived)
        return out


def _parse_json_line(msg: str) -> dict[str, Any] | None:
    """API Gateway v2 writes each access log line as a JSON object. We're
    tolerant of leading/trailing whitespace and reject anything that isn't
    a well-formed JSON dict."""
    s = msg.strip()
    if not s or not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _parse_ts(entry_ts: Any, log_ts: Any) -> datetime:
    """Prefer the caller-provided CloudWatch timestamp (ms since epoch).
    Fall back to the log line's requestTimeEpoch. Fall back to now()."""
    for candidate in (entry_ts, log_ts):
        if candidate is None:
            continue
        try:
            v = float(candidate)
        except (TypeError, ValueError):
            continue
        # API Gateway writes requestTimeEpoch as ms; sanity-check for seconds.
        if v > 1_000_000_000_000:
            v = v / 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (OverflowError, OSError):
            continue
    return datetime.now(timezone.utc)


def _int(value: Any) -> int | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _classify_scanner(ua: str | None) -> str | None:
    if not ua:
        return None
    ua_low = ua.lower()
    for sig in _SCANNER_UA_PATTERNS:
        if sig in ua_low:
            return sig
    return None


def _derive_events(
    parsed: dict[str, Any], api_name: str, ts: datetime, transport: Transport,
) -> list[Event]:
    ip = parsed.get("ip") or None
    ua = parsed.get("userAgent") or None
    method = parsed.get("httpMethod") or None
    route_key = parsed.get("routeKey") or None
    status = _int(parsed.get("status")) or 0
    integration_status = _int(parsed.get("integrationStatus"))
    resp_len = _int(parsed.get("responseLength")) or 0
    latency = _int(parsed.get("responseLatency"))
    error_msg = parsed.get("errorMessage") if parsed.get("errorMessage") not in (None, "-", "") else None
    error_type = parsed.get("errorResponseType") if parsed.get("errorResponseType") not in (None, "-", "") else None
    request_id = parsed.get("requestId") or None

    out: list[Event] = []

    # Base request event — PROJECTION_ONLY, drives source-IP tracking + burst
    # counters. Not stored.
    base_extra = {
        "api_name": api_name,
        "source_ip": ip,
        "user_agent": ua,
        "method": method,
        "route_key": route_key,
        "status": status,
        "integration_status": integration_status,
        "response_length": resp_len,
        "response_latency_ms": latency,
        "request_id": request_id,
    }
    out.append(_mkevent(
        action="api.request",
        outcome=Outcome.success if 200 <= status < 400 else Outcome.failure,
        ts=ts, api_name=api_name,
        ip=ip, ua=ua, method=method, status=status,
        extra=base_extra,
        transport=transport,
    ))

    # Client failure — any 4xx (auth failure, forbidden, not found, bad
    # body, etc). We deliberately DON'T pretend to know whether a 400 is
    # a real credential attack, a schema mismatch, or an enumeration
    # attempt — without paths (PHI-safe log format) we can't tell. Group
    # them into one bucket; the burst rule fires on any 4xx pattern from
    # one client IP. Rate limiting (429) is server-side throttling, not
    # a client-side failure — kept separate.
    if 400 <= status < 500 and status != 429:
        reason_default = {
            400: "bad_request", 401: "unauthorized", 403: "forbidden",
            404: "not_found", 405: "method_not_allowed",
            409: "conflict", 413: "payload_too_large",
            415: "unsupported_media_type", 422: "unprocessable_entity",
        }.get(status, f"client_error_{status}")
        out.append(_mkevent(
            action="api.auth.failure",
            outcome=Outcome.failure,
            ts=ts, api_name=api_name,
            ip=ip, ua=ua, method=method, status=status,
            extra={
                **base_extra,
                "reason": error_type or reason_default,
                "error_message": _truncate(error_msg),
            },
            transport=transport,
        ))

    # Server-side error — 5xx
    elif status >= 500:
        out.append(_mkevent(
            action="api.error",
            outcome=Outcome.failure,
            ts=ts, api_name=api_name,
            ip=ip, ua=ua, method=method, status=status,
            extra={
                **base_extra,
                "reason": error_type or "server_error",
                "error_message": _truncate(error_msg),
            },
            transport=transport,
        ))

    # Scanner user agent — any status. Detection is UA-based, not response-
    # based; a scanner can still succeed on some endpoints.
    scanner_sig = _classify_scanner(ua)
    if scanner_sig:
        out.append(_mkevent(
            action="api.scanner_ua",
            outcome=Outcome.failure,
            ts=ts, api_name=api_name,
            ip=ip, ua=ua, method=method, status=status,
            extra={
                **base_extra,
                "scanner_signature": scanner_sig,
                "message": (
                    f"{api_name}: request from {ip or 'unknown'} used "
                    f"known scanner signature '{scanner_sig}' "
                    f"(status {status}, method {method or '?'})"
                ),
            },
            transport=transport,
        ))

    return out


def _truncate(s: str | None, max_len: int = 300) -> str | None:
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= max_len else s[:max_len] + "…"


def _mkevent(
    *, action: str, outcome: Outcome, ts: datetime,
    api_name: str,
    ip: str | None, ua: str | None,
    method: str | None, status: int,
    extra: dict[str, Any], transport: Transport,
) -> Event:
    observables: list[Observable] = []
    if ip:
        observables.append(Observable(type="ip", value=ip))
    # NOTE: user-agent isn't in the ObservableType enum, so we don't promote
    # it here. The full UA string still lives in extra.user_agent for the
    # scanner-UA rule and the /api-gw UI to render.
    tags = {"env": "prod", "api": api_name}
    payload = {**extra, "tags": tags}
    # Deterministic event_id so at-least-once SQS delivery dedupes cleanly.
    fp_src = "|".join((
        action, api_name, ts.isoformat(),
        ip or "-", str(status), method or "-",
        extra.get("request_id") or "-",
    ))
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, fp_src))
    return Event(
        event_id=event_id,
        source=Source(module=_MODULE, transport=transport),
        event_time=ts,
        category=Category.other,
        action=action,
        outcome=outcome,
        actor=Actor(principal=None, source_ip=ip),
        target=Target(id=api_name, type="api.gateway", name=api_name),
        observables=observables,
        extra=payload,
        raw={"module": _MODULE},
    )
