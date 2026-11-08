"""Small transport-neutral models shared by later pipeline modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class ResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    INCOMPLETE = "incomplete"


class TraceCaptureStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class ToolTraceStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PRESENT = "present"
    MISSING = "missing"
    INCOMPLETE = "incomplete"


@dataclass(slots=True)
class TraceInput:
    turn_index: int
    text: str
    started_at: datetime
    completed_at: datetime | None
    request_id: str | None = None
    assistant_message_completed: bool = False


@dataclass(slots=True)
class TraceEvent:
    event_id: str
    event_type: str
    sequence: int
    agent: str | None = None
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None
    turn_index: int | None = None
    source: str | None = None
    source_event_type: str | None = None
    source_event_id: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Trace:
    trace_id: str
    run_id: str
    case_id: str
    thread_id: str | None
    sut_revision: str | None
    status: ResultStatus = ResultStatus.PENDING
    inputs: list[TraceInput] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    completeness_notes: list[str] = field(default_factory=list)
    source_limitations: list[str] = field(default_factory=list)
    schema_version: int = 1
    capture_status: TraceCaptureStatus = TraceCaptureStatus.INCOMPLETE
    tool_trace_status: ToolTraceStatus = ToolTraceStatus.NOT_REQUIRED
    source: str = "chatkit.state"
    ordering_policy: str = "snapshot_array_order"
    case_version: str | None = None
    model_name: str | None = None
    execution_mode: str | None = None
    adapter_version: str | None = None
    final_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AssertionResult:
    assertion_id: str
    name: str
    passed: bool
    severity: str
    expected: Any = None
    actual: Any = None
    evidence_event_ids: list[str] = field(default_factory=list)
    message: str = ""


@dataclass(slots=True)
class CaseResult:
    case_id: str
    run_id: str
    status: ResultStatus = ResultStatus.PENDING
    assertions: list[AssertionResult] = field(default_factory=list)
    trace_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    error_category: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class RunRecord:
    run_id: str = field(default_factory=new_id)
    status: ResultStatus = ResultStatus.PENDING
    sut_revision: str | None = None
    config_fingerprint: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    case_results: list[CaseResult] = field(default_factory=list)


@dataclass(slots=True)
class GateResult:
    run_id: str
    status: ResultStatus
    critical_failures: int = 0
    errors: int = 0
    incomplete: int = 0
    summary: str = ""

    @property
    def exit_code(self) -> int:
        if self.status == ResultStatus.PASS:
            return 0
        if self.critical_failures:
            return 1
        if self.errors:
            return 10
        if self.incomplete:
            return 5
        return 1
