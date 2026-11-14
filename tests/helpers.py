from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from typing import Any

from agent_regression_gate.cases.models import Case, Rule
from agent_regression_gate.models import (
    Trace,
    TraceCaptureStatus,
    TraceEvent,
    ToolTraceStatus,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_EVENT_IDS = count(1)


def make_rule(
    rule_type: str = "tool_must_be_called",
    *,
    rule_id: str = "R1",
    severity: str = "critical",
    **params: Any,
) -> Rule:
    return Rule(id=rule_id, type=rule_type, severity=severity, params=params)


def make_case(*rules: Rule, case_id: str = "CASE-1") -> Case:
    return Case(
        id=case_id,
        name="test case",
        risk_level="critical",
        turns=["hello"],
        rules=list(rules),
    )


def make_event(
    event_type: str,
    content: Any = None,
    *,
    event_id: str | None = None,
    agent: str = "Agent",
    metadata: dict[str, Any] | None = None,
    sequence: int | None = None,
) -> TraceEvent:
    resolved_id = event_id if event_id is not None else f"event-{next(_EVENT_IDS)}"
    return TraceEvent(
        event_id=resolved_id,
        event_type=event_type,
        sequence=sequence if sequence is not None else next(_EVENT_IDS),
        agent=agent,
        content=content,
        metadata=metadata or {},
        timestamp=NOW,
    )


def tool_call(name: str, args: dict[str, Any] | None = None, **kwargs: Any) -> TraceEvent:
    return make_event(
        "tool_call",
        name,
        metadata={"tool_args": args or {}, **kwargs.pop("metadata", {})},
        **kwargs,
    )


def tool_result(name: str = "ok", **kwargs: Any) -> TraceEvent:
    return make_event("tool_result", name, **kwargs)


def message(text: str, **kwargs: Any) -> TraceEvent:
    return make_event("message", text, **kwargs)


def handoff(target: str, source: str = "Agent", **kwargs: Any) -> TraceEvent:
    return make_event(
        "handoff",
        f"{source} -> {target}",
        metadata={"source_agent": source, "target_agent": target},
        agent=source,
        **kwargs,
    )


def make_trace(
    events: list[TraceEvent] | None = None,
    *,
    capture_status: str = "complete",
    tool_trace_status: str = "present",
    final_context: dict[str, Any] | None = None,
    case_id: str = "CASE-1",
) -> Trace:
    return Trace(
        trace_id="trace-1",
        run_id="run-1",
        case_id=case_id,
        thread_id="thread-1",
        sut_revision="rev-test",
        events=list(events or []),
        capture_status=TraceCaptureStatus(capture_status),
        tool_trace_status=ToolTraceStatus(tool_trace_status),
        final_context=final_context or {},
    )
