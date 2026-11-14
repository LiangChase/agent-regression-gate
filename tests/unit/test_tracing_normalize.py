from __future__ import annotations

from datetime import datetime, timezone

from agent_regression_gate.models import TraceCaptureStatus, ToolTraceStatus
from agent_regression_gate.sut.models import ObservedEvent, SutTraceSnapshot, SutTurnResult
from agent_regression_gate.tracing.normalize import normalize_trace
from agent_regression_gate.tracing.schema import TurnCapture

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def observed(event_id: str, event_type: str, content=None, metadata=None, agent="Triage Agent"):
    return ObservedEvent(
        event_id=event_id,
        event_type=event_type,
        agent=agent,
        content=content,
        metadata=metadata or {},
    )


def capture(
    *,
    thread_id: str = "thread-1",
    events: list[ObservedEvent] | None = None,
    guardrails: list[dict] | None = None,
    context: dict | None = None,
    agents: list[dict] | None = None,
    assistant_completed: bool = True,
):
    events = events if events is not None else [observed("e1", "message", "hello")]
    context = context or {"flight_number": "FLT-123"}
    turn = SutTurnResult(
        thread_id=thread_id,
        user_input="hello",
        started_at=NOW,
        completed_at=NOW,
        assistant_message_completed=assistant_completed,
    )
    snapshot = SutTraceSnapshot(
        thread_id=thread_id,
        current_agent="Triage Agent",
        context=context,
        agents=agents or [],
        events=events,
        guardrails=guardrails or [],
        raw_payload={"thread_id": thread_id, "context": context, "events": []},
    )
    return TurnCapture(turn=turn, snapshot=snapshot)


def normalize(captures, **kwargs):
    return normalize_trace(
        run_id="run-1",
        case_id="CASE-1",
        captures=captures,
        sut_revision="rev-1",
        **kwargs,
    )


def test_complete_trace_maps_events_and_marks_tool_status():
    bundle = normalize(
        [
            capture(
                events=[
                    observed("e1", "tool_call", "flight_status_tool", {"tool_args": {"flight_number": "FLT-123"}}),
                    observed("e2", "tool_output", "On time"),
                    observed("e3", "message", "FLT-123 is on time"),
                    observed("e4", "context_update", "", {"changes": {"flight_number": "FLT-123"}}),
                ],
                guardrails=[{"id": "g1", "name": "Relevance Guardrail", "passed": True}],
                agents=[{"name": "Triage Agent", "tools": ["flight_status_tool"]}],
            )
        ]
    )
    trace = bundle.trace
    assert trace.capture_status == TraceCaptureStatus.COMPLETE
    assert trace.tool_trace_status == ToolTraceStatus.PRESENT
    assert [event.event_type for event in trace.events] == [
        "tool_call",
        "tool_result",
        "message",
        "context_update",
        "guardrail",
    ]
    assert trace.completeness_notes == []
    assert trace.final_context == {"flight_number": "FLT-123"}


def test_cumulative_snapshots_keep_only_new_events():
    first = capture(events=[observed("e1", "message", "one")])
    second = capture(
        events=[
            observed("e1", "message", "one"),
            observed("e2", "message", "two"),
        ]
    )
    trace = normalize([first, second]).trace
    assert [event.content for event in trace.events] == ["one", "two"]


def test_missing_assistant_completion_marks_trace_incomplete():
    trace = normalize(
        [
            capture(events=[observed("e1", "message", "partial")], assistant_completed=False),
        ]
    ).trace
    assert trace.capture_status == TraceCaptureStatus.INCOMPLETE
    assert any("assistant_completion_missing" in note for note in trace.completeness_notes)


def test_thread_mismatch_marks_trace_incomplete():
    trace = normalize(
        [
            capture(thread_id="thread-1", events=[observed("e1", "message", "one")]),
            capture(thread_id="thread-2", events=[observed("e2", "message", "two")]),
        ]
    ).trace
    assert trace.capture_status == TraceCaptureStatus.INCOMPLETE
    assert any("thread_id_mismatch" in note for note in trace.completeness_notes)


def test_tool_call_without_result_marks_tool_trace_incomplete():
    trace = normalize(
        [
            capture(events=[observed("e1", "tool_call", "flight_status_tool", {"tool_args": {}})]),
        ]
    ).trace
    assert trace.tool_trace_status == ToolTraceStatus.INCOMPLETE
    assert any("tool_call_result_count_mismatch" in note for note in trace.completeness_notes)


def test_required_tool_trace_missing_marks_capture_incomplete():
    trace = normalize(
        [
            capture(events=[observed("e1", "message", "no tools")]),
        ],
        require_tool_trace=True,
    ).trace
    assert trace.tool_trace_status == ToolTraceStatus.MISSING
    assert trace.capture_status == TraceCaptureStatus.INCOMPLETE
    assert "required_tool_trace_missing" in trace.completeness_notes


def test_optional_tool_trace_missing_is_allowed():
    trace = normalize(
        [
            capture(events=[observed("e1", "message", "no tools")]),
        ],
        require_tool_trace=False,
    ).trace
    assert trace.tool_trace_status == ToolTraceStatus.NOT_REQUIRED
    assert trace.capture_status == TraceCaptureStatus.COMPLETE


def test_no_turn_captures_marks_trace_incomplete():
    trace = normalize([]).trace
    assert trace.capture_status == TraceCaptureStatus.INCOMPLETE
    assert "no_turn_captures" in trace.completeness_notes


def test_empty_snapshot_marks_trace_incomplete():
    trace = normalize([capture(events=[], guardrails=[])]).trace
    assert trace.capture_status == TraceCaptureStatus.INCOMPLETE
    assert any("no_agent_events_or_guardrails" in note for note in trace.completeness_notes)
