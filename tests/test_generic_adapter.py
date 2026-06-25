"""Unit tests for the normalized event + generic adapter. No DB required."""

from blackwatch.event import Severity, compute_fingerprint
from blackwatch.modules.base import IngestContext
from blackwatch.modules.generic import GenericAdapter


def _ctx(**kw):
    return IngestContext(module=kw.pop("module", "generic"), **kw)


def test_generic_normalizes_known_fields():
    adapter = GenericAdapter()
    events = adapter.parse(
        {
            "action": "iam.policy.attach",
            "category": "iam",
            "outcome": "success",
            "actor": {"principal": "arn:aws:iam::123:user/dave", "source_ip": "203.0.113.5"},
            "target": {"id": "arn:aws:iam::aws:policy/AdministratorAccess", "type": "iam.policy"},
        },
        _ctx(transport="webhook"),
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.action == "iam.policy.attach"
    assert ev.category.value == "iam"
    assert ev.outcome.value == "success"
    assert ev.actor.principal == "arn:aws:iam::123:user/dave"
    assert ev.target.type == "iam.policy"
    # Severity is never set by an adapter.
    assert ev.severity is None
    # Raw payload is preserved verbatim.
    assert ev.raw["action"] == "iam.policy.attach"


def test_fingerprint_is_deterministic_and_set():
    adapter = GenericAdapter()
    payload = {"action": "a.b", "actor": {"principal": "p"}, "target": {"id": "t"}}
    ev = adapter.parse(payload, _ctx())[0]
    assert ev.dedup_fingerprint == compute_fingerprint("a.b", "p", "t")


def test_clamav_finding_maps_cleanly():
    adapter = GenericAdapter()
    ev = adapter.parse(
        {
            "vendor": "clamav",
            "category": "finding",
            "action": "finding.malware.detected",
            "outcome": "success",
            "target": {"id": "s3://finance-uploads/q3/invoice.xlsx", "type": "s3.object"},
            "observables": [{"type": "bucket", "value": "finance-uploads"}],
            "extra": {"signature": "Win.Trojan.Foo"},
        },
        _ctx(module="custom.clamav", transport="webhook"),
    )[0]
    assert ev.source.module == "custom.clamav"
    assert ev.source.vendor == "clamav"
    assert ev.category.value == "finding"
    assert ev.observables[0].value == "finance-uploads"
    assert ev.extra["signature"] == "Win.Trojan.Foo"
    assert ev.severity is None  # a rule will set this to critical later


def test_unknown_severity_enum_unused_in_phase0():
    # Sanity that the enum exists for the rule engine to use later.
    assert Severity.critical.value == "critical"
