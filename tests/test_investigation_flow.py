from __future__ import annotations

import unittest
from types import SimpleNamespace


class InvestigationFlowTests(unittest.TestCase):
    def test_creating_ip_investigation_queues_initial_scan(self):
        from blackwatch.investigation_flow import create_initial_scan

        created = {
            "id": "case-1",
            "title": "Investigate 8.8.8.8",
            "status": "ready",
            "observables": ["ip:8.8.8.8"],
        }
        queued = {
            "id": "scan-1",
            "status": "queued",
            "result_count": 0,
            "error": None,
        }
        calls: list[tuple[str, str]] = []
        statuses: list[tuple[str, str]] = []

        storage = SimpleNamespace(
            update_investigation_status=lambda investigation_id, status: statuses.append(
                (str(investigation_id), status)
            ),
            create_investigation_scan=lambda **kwargs: calls.append(
                (str(kwargs["investigation_id"]), kwargs["requested_by"])
            ) or queued
        )
        result = create_initial_scan(
            storage,
            investigation_id="case-1",
            requested_by="alice",
            row=created,
        )

        self.assertEqual(calls, [("case-1", "alice")])
        self.assertEqual(statuses, [("case-1", "investigating")])
        self.assertEqual(result["id"], "case-1")
        self.assertEqual(result["status"], "investigating")
        self.assertEqual(result["scan"], queued)
