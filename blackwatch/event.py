"""The Normalized Event — the frozen contract every adapter produces and the
core consumes. See docs/EVENT_SCHEMA.md. Changes here must be ADDITIVE ONLY."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Transport(str, Enum):
    webhook = "webhook"
    aws_lambda = "lambda"
    poll = "poll"
    syslog = "syslog"
    queue = "queue"
    api = "api"
    file = "file"


class Category(str, Enum):
    iam = "iam"
    network = "network"
    storage = "storage"
    auth = "auth"
    compute = "compute"
    vpn = "vpn"
    host = "host"
    finding = "finding"
    audit = "audit"
    other = "other"


class Outcome(str, Enum):
    success = "success"
    failure = "failure"
    unknown = "unknown"


class ActorType(str, Enum):
    user = "user"
    role = "role"
    service = "service"
    root = "root"
    system = "system"
    unknown = "unknown"


class Severity(str, Enum):
    informational = "informational"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


_SEVERITY_ORDER = ["informational", "low", "medium", "high", "critical"]


def severity_rank(severity: "Severity | str | None") -> int:
    """Ordinal rank for comparison. None / unknown -> -1 (below everything)."""
    if severity is None:
        return -1
    value = severity.value if isinstance(severity, Severity) else str(severity)
    return _SEVERITY_ORDER.index(value) if value in _SEVERITY_ORDER else -1


class ObservableType(str, Enum):
    ip = "ip"
    arn = "arn"
    access_key = "access_key"
    bucket = "bucket"
    hash = "hash"
    domain = "domain"
    email = "email"
    hostname = "hostname"
    user = "user"


class Source(BaseModel):
    module: str
    vendor: str | None = None
    account: str | None = None
    region: str | None = None
    transport: Transport = Transport.webhook


class Actor(BaseModel):
    principal: str | None = None
    type: ActorType | None = None
    is_root: bool | None = None
    via_role: str | None = None
    source_ip: str | None = None
    user_agent: str | None = None


class Target(BaseModel):
    id: str | None = None
    type: str | None = None
    name: str | None = None


class Observable(BaseModel):
    type: ObservableType
    value: str


class Event(BaseModel):
    """The normalized event envelope. `severity` is intentionally None until a
    detection rule sets it — sources never declare how bad something is."""

    # Identity
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: int = SCHEMA_VERSION
    dedup_fingerprint: str = ""

    # Time
    event_time: datetime = Field(default_factory=_now)
    ingested_at: datetime = Field(default_factory=_now)

    # Source / classification
    source: Source
    category: Category = Category.other
    action: str = "generic.event"
    outcome: Outcome = Outcome.unknown

    # Actor / target / observables
    actor: Actor = Field(default_factory=Actor)
    target: Target = Field(default_factory=Target)
    observables: list[Observable] = Field(default_factory=list)

    # Assessment (filled by rules, not adapters)
    severity: Severity | None = None
    rule_matches: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Payload
    raw: Any = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_fingerprint(self) -> "Event":
        if not self.dedup_fingerprint:
            self.dedup_fingerprint = compute_fingerprint(
                self.action, self.actor.principal, self.target.id
            )
        return self


def compute_fingerprint(action: str, principal: str | None, target_id: str | None) -> str:
    basis = f"{action}|{principal or ''}|{target_id or ''}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
