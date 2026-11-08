"""Versioned, transport-neutral case definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Rule:
    id: str
    type: str
    severity: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(slots=True)
class Case:
    id: str
    name: str
    risk_level: str
    turns: list[str]
    rules: list[Rule]
    version: str = "1"
    tags: list[str] = field(default_factory=list)
    description: str = ""
    timeout_seconds: float = 120.0
    requires_tool_trace: bool = False
    base_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CaseCollection:
    cases: list[Case]
    source_files: list[str]

