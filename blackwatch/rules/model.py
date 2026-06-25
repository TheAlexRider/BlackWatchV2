"""Declarative rule model. Rules are data (YAML), not code — operators are a
small fixed set (see operators.py). A rule's `match` is a recursive Condition
supporting all/any/not nesting plus leaf {field, op, value} comparisons."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..event import Severity


class Condition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Leaf form
    field: str | None = None
    op: str | None = None
    value: Any = None

    # Group forms
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None
    not_: "Condition | None" = Field(default=None, alias="not")


class Rule(BaseModel):
    id: str
    title: str = ""
    description: str = ""
    enabled: bool = True
    # "alert" assigns severity/tags; "suppress" forces informational + tags the
    # event as suppressed (allowlist behavior) and wins over any alert rule.
    action: Literal["alert", "suppress"] = "alert"
    severity: Severity | None = None
    tags: list[str] = Field(default_factory=list)
    match: Condition


Condition.model_rebuild()
