"""The fixed operator vocabulary for rule leaves. Deliberately small — this is
NOT a general expression language. Each operator takes (field_value, expected)
and returns a bool. Operators are total: a missing (None) field never raises."""

from __future__ import annotations

import ipaddress
import re
from typing import Any


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def op_equals(field: Any, expected: Any) -> bool:
    return field == expected


def op_not_equals(field: Any, expected: Any) -> bool:
    return field != expected


def op_in(field: Any, expected: Any) -> bool:
    choices = _as_list(expected)
    if isinstance(field, list):
        return any(item in choices for item in field)
    return field in choices


def op_not_in(field: Any, expected: Any) -> bool:
    """Inverse of op_in. A None / missing field counts as "not in" — useful for
    "field is in this allowlist of expected values" rules where the event
    legitimately lacks the field (don't fire), vs an unexpected value (fire)."""
    if field is None:
        return False
    return not op_in(field, expected)


def op_contains(field: Any, expected: Any) -> bool:
    if field is None:
        return False
    if isinstance(field, list):
        return expected in field
    return str(expected) in str(field)


def op_icontains(field: Any, expected: Any) -> bool:
    if field is None:
        return False
    return str(expected).lower() in str(field).lower()


def op_regex(field: Any, expected: Any) -> bool:
    if field is None:
        return False
    return re.search(str(expected), str(field)) is not None


def op_cidr(field: Any, expected: Any) -> bool:
    if field is None:
        return False
    try:
        network = ipaddress.ip_network(str(expected), strict=False)
    except ValueError:
        return False

    def _hit(addr: Any) -> bool:
        try:
            return ipaddress.ip_address(str(addr)) in network
        except ValueError:
            return False

    if isinstance(field, list):
        return any(_hit(item) for item in field)
    return _hit(field)


def op_exists(field: Any, expected: Any) -> bool:
    return field is not None


def op_startswith(field: Any, expected: Any) -> bool:
    return isinstance(field, str) and field.startswith(str(expected))


def op_endswith(field: Any, expected: Any) -> bool:
    return isinstance(field, str) and field.endswith(str(expected))


OPERATORS = {
    "equals": op_equals,
    "not_equals": op_not_equals,
    "in": op_in,
    "not_in": op_not_in,
    "contains": op_contains,
    "icontains": op_icontains,
    "regex": op_regex,
    "cidr": op_cidr,
    "exists": op_exists,
    "startswith": op_startswith,
    "endswith": op_endswith,
}
