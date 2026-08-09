"""UEBA config loader — reads rules/ueba.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

_DIMENSIONS = (
    "source_ip",
    "source_country",
    "source_asn",
    "hour_of_day",
    "action",
    "user_agent_family",
)

_DEFAULT_WARM_UP_DAYS = 7


@dataclass
class DimensionConfig:
    enabled: bool = True
    warm_up_days: int = _DEFAULT_WARM_UP_DAYS


@dataclass
class UebaConfig:
    dimensions: dict[str, DimensionConfig] = field(default_factory=dict)
    principal_type_allow: list[str] = field(default_factory=list)
    principal_type_deny: list[str] = field(default_factory=list)
    default_warm_up_days: int = _DEFAULT_WARM_UP_DAYS

    def dim(self, name: str) -> DimensionConfig:
        return self.dimensions.get(name, DimensionConfig(warm_up_days=self.default_warm_up_days))

    def principal_allowed(self, ptype: str) -> bool:
        if self.principal_type_deny and ptype in self.principal_type_deny:
            return False
        if self.principal_type_allow and ptype not in self.principal_type_allow:
            return False
        return True


_cached: UebaConfig | None = None
_cached_mtime: float | None = None


def _config_path() -> str:
    rules_dir = os.environ.get("RULES_DIR", "rules")
    return os.path.join(rules_dir, "ueba.yaml")


def load(force: bool = False) -> UebaConfig:
    global _cached, _cached_mtime
    path = _config_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if not force and _cached is not None and mtime == _cached_mtime:
        return _cached

    data: dict[str, Any] = {}
    if mtime is not None:
        try:
            with open(path, encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
        except Exception:
            data = {}

    default_warm = int(data.get("default_warm_up_days", _DEFAULT_WARM_UP_DAYS))
    dims_raw = data.get("dimensions") or {}
    dims: dict[str, DimensionConfig] = {}
    for name in _DIMENSIONS:
        entry = dims_raw.get(name) or {}
        dims[name] = DimensionConfig(
            enabled=bool(entry.get("enabled", True)),
            warm_up_days=int(entry.get("warm_up_days", default_warm)),
        )
    cfg = UebaConfig(
        dimensions=dims,
        principal_type_allow=list(data.get("principal_type_allow") or []),
        principal_type_deny=list(data.get("principal_type_deny") or []),
        default_warm_up_days=default_warm,
    )
    _cached, _cached_mtime = cfg, mtime
    return cfg


def dimension_names() -> tuple[str, ...]:
    return _DIMENSIONS
