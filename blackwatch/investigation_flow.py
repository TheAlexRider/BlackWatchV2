"""Small orchestration helpers for durable investigation entry points."""

from __future__ import annotations

import uuid
from typing import Any, Protocol


class InvestigationScanStore(Protocol):
    def update_investigation_status(self, investigation_id: uuid.UUID, status: str) -> None: ...

    def create_investigation_scan(
        self, *, scan_id: uuid.UUID, investigation_id: uuid.UUID, requested_by: str
    ) -> dict[str, Any]: ...


def create_initial_scan(
    store: InvestigationScanStore,
    *,
    investigation_id: uuid.UUID,
    requested_by: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Queue the first scan and return the case with its scan state attached."""

    store.update_investigation_status(investigation_id, "investigating")
    scan = store.create_investigation_scan(
        scan_id=uuid.uuid4(),
        investigation_id=investigation_id,
        requested_by=requested_by,
    )
    return {**row, "status": "investigating", "scan": scan}
