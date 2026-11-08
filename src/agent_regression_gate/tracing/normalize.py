"""Normalize SUT snapshots into ordered, transport-neutral Gate traces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ..errors import ConfigurationError
from ..models import (
    ResultStatus,
    ToolTraceStatus,
    Trace,
    TraceCaptureStatus,
    TraceEvent,
    TraceInput,
    new_id,
)
from .schema import RAW_SNAPSHOT_SCHEMA_VERSION, TraceBundle, TurnCapture, to_jsonable

_EVENT_TYPE_MAP = {
    "message": "message",
    "handoff": "handoff",
    "tool_call": "tool_call",
    "tool_output": "tool_result",
    "error": "error",
    "context_update": "context_update",
}
_TOOL_ALLOWLIST_MARKER = "gate_tool_allowlisted_for_agent"


def normalize_trace(
    *,
    run_id: str,
    case_id: str,
    captures: Sequence[TurnCapture],
    sut_revision: str | None,
    case_version: str | None = None,
    model_name: str | None = None,
    execution_mode: str | None = None,
    adapter_version: str = "1",
    require_tool_trace: bool = False,
    trace_id: str | None = None,
) -> TraceBundle:
    """Build a trace from each turn's receipt and immediately collected snapshot.

    Event array order from the SUT is authoritative. Per-turn snapshots can be
    cumulative; event IDs are used to retain only newly observed events.
    """
    if not run_id.strip() or not case_id.strip():
        raise ConfigurationError("run_id and case_id are required to normalize a trace.")

    trace_id = trace_id or new_id()
    notes: list[str] = []
    inputs: list[TraceInput] = []
    events: list[TraceEvent] = []
    raw_snapshots: list[dict[str, Any]] = []
    source_limitations: list[str] = []
    first_thread_id: str | None = None
    previous_event_signatures: list[str] = []
    seen_event_ids: set[str] = set()
    tool_names = _tool_names(captures)
    tool_catalog = _tool_catalog(captures)
    turn_is_complete = bool(captures)

    for turn_index, capture in enumerate(captures, start=1):
        turn = capture.turn
        snapshot = capture.snapshot
        if first_thread_id is None:
            first_thread_id = snapshot.thread_id
        if turn.thread_id != snapshot.thread_id or snapshot.thread_id != first_thread_id:
            notes.append(f"turn_{turn_index}:thread_id_mismatch")
            turn_is_complete = False
        if not turn.assistant_message_completed:
            notes.append(f"turn_{turn_index}:assistant_completion_missing")
            turn_is_complete = False
        if not snapshot.events and not snapshot.guardrails:
            notes.append(f"turn_{turn_index}:no_agent_events_or_guardrails")
            turn_is_complete = False

        inputs.append(
            TraceInput(
                turn_index=turn_index,
                text=turn.user_input,
                started_at=turn.started_at,
                completed_at=turn.completed_at,
                request_id=turn.request_id,
                assistant_message_completed=turn.assistant_message_completed,
            )
        )

        current_events = list(snapshot.events)
        current_signatures = [_event_signature(event) for event in current_events]
        new_events: list[Any]
        if len(current_signatures) >= len(previous_event_signatures) and (
            current_signatures[: len(previous_event_signatures)] == previous_event_signatures
        ):
            new_events = current_events[len(previous_event_signatures) :]
        elif all(event.event_id for event in current_events):
            new_events = [event for event in current_events if event.event_id not in seen_event_ids]
            notes.append(f"turn_{turn_index}:snapshot_not_append_only_used_event_ids")
            if not new_events and current_events:
                turn_is_complete = False
        else:
            new_events = current_events
            notes.append(f"turn_{turn_index}:snapshot_rewritten_without_event_ids")
            turn_is_complete = False

        if not new_events and not snapshot.guardrails:
            notes.append(f"turn_{turn_index}:no_new_turn_evidence")
            turn_is_complete = False

        for observed in new_events:
            if observed.event_id and observed.event_id in seen_event_ids:
                continue
            if observed.event_id:
                seen_event_ids.add(observed.event_id)
            events.append(_normalize_event(observed, len(events) + 1, turn_index, tool_names, tool_catalog, notes))

        for guardrail in snapshot.guardrails:
            guardrail_id = guardrail.get("id")
            event_id = guardrail_id if isinstance(guardrail_id, str) else f"{trace_id}-guardrail-{turn_index}-{len(events)+1}"
            events.append(
                TraceEvent(
                    event_id=event_id,
                    event_type="guardrail",
                    sequence=len(events) + 1,
                    agent=snapshot.current_agent,
                    content=guardrail.get("name"),
                    metadata={
                        key: value
                        for key, value in guardrail.items()
                        if key not in {"id", "name", "timestamp"}
                    },
                    timestamp=_parse_timestamp(guardrail.get("timestamp")),
                    turn_index=turn_index,
                    source="chatkit.guardrails",
                    source_event_type="guardrail",
                    source_event_id=guardrail_id if isinstance(guardrail_id, str) else None,
                )
            )

        previous_event_signatures = current_signatures
        raw_payload = snapshot.raw_payload or _reconstruct_snapshot(snapshot)
        raw_snapshots.append(
            {
                "schema_version": RAW_SNAPSHOT_SCHEMA_VERSION,
                "source": "chatkit.state",
                "run_id": run_id,
                "case_id": case_id,
                "thread_id": snapshot.thread_id,
                "turn_index": turn_index,
                "turn": to_jsonable(turn),
                "unknown_sse_events": to_jsonable(turn.unknown_events),
                "snapshot": to_jsonable(raw_payload),
            }
        )

    real_tool_calls = [
        event for event in events
        if event.event_type == "tool_call" and event.metadata.get("classification") != "handoff_callback"
    ]
    tool_results = [event for event in events if event.event_type == "tool_result"]
    if not real_tool_calls and not tool_results:
        tool_status = ToolTraceStatus.MISSING if require_tool_trace else ToolTraceStatus.NOT_REQUIRED
    elif len(real_tool_calls) != len(tool_results):
        tool_status = ToolTraceStatus.INCOMPLETE
        notes.append(f"tool_call_result_count_mismatch:{len(real_tool_calls)}:{len(tool_results)}")
        turn_is_complete = False
    else:
        tool_status = ToolTraceStatus.PRESENT
    if require_tool_trace and tool_status == ToolTraceStatus.MISSING:
        notes.append("required_tool_trace_missing")
        turn_is_complete = False

    if captures:
        source_limitations.append(
            "SUT AgentEvent content and tool output may already be truncated at source."
        )
        started_at = captures[0].turn.started_at
        completed_at = captures[-1].turn.completed_at
        final_context = dict(captures[-1].snapshot.context)
    else:
        notes.append("no_turn_captures")
        started_at = datetime.now(timezone.utc)
        completed_at = None
        final_context = {}
        turn_is_complete = False

    capture_status = (
        TraceCaptureStatus.COMPLETE if turn_is_complete else TraceCaptureStatus.INCOMPLETE
    )
    trace = Trace(
        trace_id=trace_id,
        run_id=run_id,
        case_id=case_id,
        thread_id=first_thread_id,
        sut_revision=sut_revision,
        status=ResultStatus.PENDING if turn_is_complete else ResultStatus.INCOMPLETE,
        inputs=inputs,
        events=events,
        started_at=started_at,
        completed_at=completed_at,
        completeness_notes=notes,
        source_limitations=source_limitations,
        schema_version=1,
        capture_status=capture_status,
        tool_trace_status=tool_status,
        source="chatkit.state",
        ordering_policy="SUT snapshot array order; cumulative snapshots de-duplicated by event ID",
        case_version=case_version,
        model_name=model_name,
        execution_mode=execution_mode,
        adapter_version=adapter_version,
        final_context=final_context,
    )
    return TraceBundle(trace=trace, raw_snapshots=raw_snapshots)


def _normalize_event(
    observed: Any,
    sequence: int,
    turn_index: int,
    tool_names: set[str],
    tool_catalog: dict[str, set[str]],
    notes: list[str],
) -> TraceEvent:
    source_type = observed.event_type
    metadata = dict(observed.metadata)
    event_type = _EVENT_TYPE_MAP.get(source_type, "unknown")
    if source_type == "tool_call":
        name = observed.content if isinstance(observed.content, str) else ""
        has_arguments = "tool_args" in metadata
        if not has_arguments and name not in tool_names:
            event_type = "handoff_callback"
            metadata["classification"] = "handoff_callback"
        else:
            allowed_tools = tool_catalog.get(observed.agent or "")
            metadata[_TOOL_ALLOWLIST_MARKER] = bool(allowed_tools is not None and name in allowed_tools)
            if not metadata[_TOOL_ALLOWLIST_MARKER]:
                notes.append(f"event_{sequence}:tool_not_in_agent_catalog:{name or 'unknown'}")
    if event_type == "unknown":
        metadata["original_event_type"] = source_type
    source_id = observed.event_id if isinstance(observed.event_id, str) else None
    event_id = source_id or f"local-event-{sequence:06d}"
    return TraceEvent(
        event_id=event_id,
        event_type=event_type,
        sequence=sequence,
        agent=observed.agent,
        content=observed.content,
        metadata=metadata,
        timestamp=_parse_timestamp(observed.timestamp),
        turn_index=turn_index,
        source="chatkit.state",
        source_event_type=source_type,
        source_event_id=source_id,
        extra_fields=dict(observed.extra_fields),
    )


def _tool_names(captures: Sequence[TurnCapture]) -> set[str]:
    names: set[str] = set()
    for capture in captures:
        for agent in capture.snapshot.agents:
            tools = agent.get("tools", [])
            if isinstance(tools, list):
                names.update(item for item in tools if isinstance(item, str))
    return names


def _tool_catalog(captures: Sequence[TurnCapture]) -> dict[str, set[str]]:
    catalog: dict[str, set[str]] = {}
    for capture in captures:
        for agent in capture.snapshot.agents:
            name = agent.get("name")
            tools = agent.get("tools", [])
            if isinstance(name, str) and isinstance(tools, list):
                catalog.setdefault(name, set()).update(item for item in tools if isinstance(item, str))
    return catalog


def _event_signature(event: Any) -> str:
    if event.event_id:
        return f"id:{event.event_id}"
    return json.dumps(
        to_jsonable(event), ensure_ascii=False, sort_keys=True, default=str
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            # This SUT emits epoch milliseconds; normalize to UTC for display.
            return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _reconstruct_snapshot(snapshot: Any) -> dict[str, Any]:
    return {
        "thread_id": snapshot.thread_id,
        "current_agent": snapshot.current_agent,
        "context": snapshot.context,
        "agents": snapshot.agents,
        "events": [
            {
                "id": event.event_id,
                "type": event.event_type,
                "agent": event.agent,
                "content": event.content,
                "metadata": event.metadata,
                "timestamp": event.timestamp,
                **event.extra_fields,
            }
            for event in snapshot.events
        ],
        "guardrails": snapshot.guardrails,
        **snapshot.extra_fields,
    }
