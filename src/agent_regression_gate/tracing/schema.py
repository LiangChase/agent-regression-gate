"""Versioned trace bundle schema and JSON-safe conversion helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ..models import Trace

TRACE_SCHEMA_VERSION = 1
RAW_SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(slots=True)
class TurnCapture:
    """One completed user turn and the SUT snapshot collected immediately after it."""

    turn: Any
    snapshot: Any


@dataclass(slots=True)
class TraceBundle:
    """Normalized evaluator-facing trace paired with parsed raw SUT snapshots."""

    trace: Trace
    raw_snapshots: list[dict[str, Any]]
    schema_version: int = TRACE_SCHEMA_VERSION

    def to_document(self, *, include_raw: bool = True) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace": to_jsonable(self.trace),
            "raw_snapshots": to_jsonable(self.raw_snapshots) if include_raw else [],
            "raw_snapshots_included": include_raw,
        }


def to_jsonable(value: Any) -> Any:
    """Convert trace values to JSON primitives without losing mapping fields."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [to_jsonable(item) for item in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"[BINARY {len(value)} bytes omitted]"
    return str(value)
