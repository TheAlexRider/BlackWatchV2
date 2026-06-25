"""Notification rules — legacy-Route → Condition migration + rule loading."""

from blackwatch.event import Severity
from blackwatch.notify.model import Route
from blackwatch.notify.router import route_to_condition


def test_min_severity_becomes_in_clause():
    cond = route_to_condition(Route(name="r", min_severity=Severity.high, channels=["t"]))
    assert cond == {"field": "severity", "op": "in", "value": ["high", "critical"]}


def test_categories_only():
    cond = route_to_condition(Route(name="r", categories=["finding"], channels=["t"]))
    assert cond == {"field": "category", "op": "in", "value": ["finding"]}


def test_multiple_clauses_wrap_in_all():
    cond = route_to_condition(
        Route(name="r", min_severity=Severity.high, modules=["aws.iam"], channels=["t"])
    )
    assert "all" in cond
    assert len(cond["all"]) == 2


def test_empty_route_matches_anything_via_exists():
    cond = route_to_condition(Route(name="r", channels=["t"]))
    assert cond == {"field": "action", "op": "exists"}


def test_severity_list_passthrough():
    cond = route_to_condition(
        Route(name="r", severity=[Severity.high, Severity.critical], channels=["t"])
    )
    assert cond == {"field": "severity", "op": "in", "value": ["high", "critical"]}


def test_tags_become_in_clause():
    cond = route_to_condition(Route(name="r", tags=["expected-automation"], channels=["t"]))
    assert cond == {"field": "tags", "op": "in", "value": ["expected-automation"]}
