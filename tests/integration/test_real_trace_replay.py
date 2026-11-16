"""Replay frozen real SUT traces through the current Gate judgment.

These fixtures are sanitized traces captured from the pinned SUT. They protect
the deterministic evaluator and trace contract from silent semantic changes
without calling a model or requiring the live SUT.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from agent_regression_gate.cases.loader import load_cases
from agent_regression_gate.evaluators.deterministic import evaluate_case
from agent_regression_gate.models import (
    ResultStatus,
    ToolTraceStatus,
    Trace,
    TraceCaptureStatus,
    TraceEvent,
)
from agent_regression_gate.tracing.storage import TraceStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "real_traces"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
CASES = load_cases(REPO_ROOT / "cases" / "airline")
CASES_BY_ID = {case.id: case for case in CASES.cases}


def _trace_from_document(document: dict) -> Trace:
    data = document["trace"]
    events = []
    for event in data.get("events", []):
        timestamp = event.get("timestamp")
        events.append(
            TraceEvent(
                event_id=str(event["event_id"]),
                event_type=str(event["event_type"]),
                sequence=int(event["sequence"]),
                agent=event.get("agent"),
                content=event.get("content"),
                metadata=event.get("metadata") or {},
                timestamp=datetime.fromisoformat(timestamp) if timestamp else None,
                turn_index=event.get("turn_index"),
                source=event.get("source"),
                source_event_type=event.get("source_event_type"),
                source_event_id=event.get("source_event_id"),
                extra_fields=event.get("extra_fields") or {},
            )
        )
    completed_at = data.get("completed_at")
    return Trace(
        trace_id=str(data["trace_id"]),
        run_id=str(data["run_id"]),
        case_id=str(data["case_id"]),
        thread_id=data.get("thread_id"),
        sut_revision=data.get("sut_revision"),
        status=ResultStatus(data.get("status", "pending")),
        events=events,
        started_at=datetime.fromisoformat(data["started_at"]),
        completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
        completeness_notes=data.get("completeness_notes") or [],
        source_limitations=data.get("source_limitations") or [],
        schema_version=int(data.get("schema_version", 1)),
        capture_status=TraceCaptureStatus(data["capture_status"]),
        tool_trace_status=ToolTraceStatus(data["tool_trace_status"]),
        source=data.get("source", "chatkit.state"),
        ordering_policy=data.get("ordering_policy", "snapshot_array_order"),
        case_version=data.get("case_version"),
        model_name=data.get("model_name"),
        execution_mode=data.get("execution_mode"),
        adapter_version=data.get("adapter_version"),
        final_context=data.get("final_context") or {},
    )


@pytest.mark.parametrize(
    "entry",
    MANIFEST["cases"],
    ids=[entry["case_id"] for entry in MANIFEST["cases"]],
)
def test_real_trace_replay_matches_frozen_judgment(entry, tmp_path):
    trace_path = FIXTURES / entry["trace"]
    # The production loader also validates the trace and raw-snapshot schema.
    document = TraceStore(tmp_path).load_document(trace_path)
    assert document["trace"]["case_id"] == entry["case_id"]

    trace = _trace_from_document(document)
    assert trace.capture_status.value == entry["capture_status"]
    assert trace.tool_trace_status.value == entry["tool_trace_status"]
    assert trace.sut_revision == MANIFEST["sut_revision"]

    case = CASES_BY_ID[entry["case_id"]]
    assert trace.case_version == case.version
    results = evaluate_case(case, trace)
    actual = {result.assertion_id: result.passed for result in results}
    assert actual == entry["expected"]
    assert set(actual) == {rule.id for rule in case.rules}


def test_real_trace_replay_covers_every_critical_case():
    critical = {case.id for case in CASES.cases if case.risk_level == "critical"}
    replayed = {entry["case_id"] for entry in MANIFEST["cases"]}
    assert replayed == critical


def test_real_trace_fixtures_are_sanitized():
    token = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
    authorization = re.compile(r"(?i)authorization")
    for entry in MANIFEST["cases"]:
        text = (FIXTURES / entry["trace"]).read_text(encoding="utf-8")
        assert token.search(text) is None
        assert authorization.search(text) is None
