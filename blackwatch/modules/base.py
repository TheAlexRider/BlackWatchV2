"""The module/adapter contract — the second frozen interface (after the event
envelope). An adapter is a PURE transform: raw payload -> normalized events.

Rules enforced by convention (keep them true):
  * No side effects. Adapters do not touch the DB, send notifications, or call
    out to AWS. They only transform bytes into Event objects.
  * Transport-agnostic. The transport that delivered the payload is passed in
    via IngestContext as metadata; adapters must not branch core behavior on it.
  * Severity-free. Adapters never set Event.severity — that is a rule decision.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from ..event import Event


class IngestContext(BaseModel):
    """Delivery context handed to an adapter at parse time."""

    module: str
    transport: str = "webhook"
    account: str | None = None
    region: str | None = None


class Adapter(ABC):
    """Base class for all telemetry adapters. Subclasses set `module` and
    implement `parse`."""

    module: str

    @abstractmethod
    def parse(self, raw: Any, ctx: IngestContext) -> list[Event]:
        """Transform a raw payload into zero or more normalized events."""
        raise NotImplementedError
