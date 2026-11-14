from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent_regression_gate.cases.models import Case, Rule
from agent_regression_gate.config import GateConfig, ModelConfig, RunConfig, SutConfig, TraceConfig
from agent_regression_gate.errors import ProtocolError, SutUnavailableError
from agent_regression_gate.execution.runner import run_suite
from agent_regression_gate.sut.models import (
    HealthStatus,
    ObservedEvent,
    SutSession,
    SutTraceSnapshot,
    SutTurnResult,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def observed(event_id: str, event_type: str, content=None, metadata=None):
    return ObservedEvent(
        event_id=event_id,
        event_type=event_type,
        agent="Triage Agent",
        content=content,
        metadata=metadata or {},
    )


def turn_script(*, tool: str | None = None, output: bool = True, error: Exception | None = None):
    events = [observed("e1", "message", "done")]
    if tool:
        events = [
            observed("e1", "tool_call", tool, {"tool_args": {"x": 1}}),
            observed("e2", "tool_output", "tool result"),
            observed("e3", "message", "done"),
        ]
        if not output:
            events = events[:1]
    return {
        "events": events,
        "assistant_completed": True,
        "error": error,
        "tool": tool,
    }


@dataclass
class FakeLifecycle:
    fail: bool = False
    started: bool = False
    stopped: bool = False

    async def start(self):
        self.started = True
        if self.fail:
            raise SutUnavailableError("fake lifecycle failed")

    async def stop(self):
        self.stopped = True


class FakeAdapter:
    def __init__(self, scripts):
        self.scripts = scripts
        self.sessions: list[SutSession] = []
        self.thread_to_index: dict[str, int] = {}
        self.send_inputs: list[str] = []
        self.send_calls = 0
        self.closed_sessions: list[str] = []
        self.aclose_called = False
        self.turn_index: dict[str, int] = {}

    async def health_check(self):
        return HealthStatus(healthy=True, status_code=200, latency_ms=0)

    async def create_session(self):
        index = len(self.sessions)
        session = SutSession(thread_id=f"thread-{index}")
        self.sessions.append(session)
        self.thread_to_index[session.thread_id] = index
        self.turn_index[session.thread_id] = 0
        return session

    async def send_turn(self, session, user_input):
        self.send_calls += 1
        self.send_inputs.append(user_input)
        script = self.scripts[self.thread_to_index[session.thread_id]][self.turn_index[session.thread_id]]
        if script["error"] is not None:
            raise script["error"]
        return SutTurnResult(
            thread_id=session.thread_id,
            user_input=user_input,
            started_at=NOW,
            completed_at=NOW,
            assistant_message_completed=script["assistant_completed"],
        )

    async def fetch_trace(self, session, *, require_activity=None):
        script = self.scripts[self.thread_to_index[session.thread_id]][self.turn_index[session.thread_id]]
        self.turn_index[session.thread_id] += 1
        tool = script["tool"]
        return SutTraceSnapshot(
            thread_id=session.thread_id,
            current_agent="Triage Agent",
            context={"flight_number": "FLT-123"},
            agents=[
                {
                    "name": "Triage Agent",
                    "tools": [tool] if tool else [],
                }
            ],
            events=script["events"],
            guardrails=[],
            raw_payload={
                "thread_id": session.thread_id,
                "context": {"flight_number": "FLT-123"},
                "events": [],
            },
        )

    async def close_session(self, session):
        self.closed_sessions.append(session.thread_id)

    async def aclose(self):
        self.aclose_called = True


def case(case_id: str, *, rule: Rule, turns=None, requires_tool_trace: bool = False) -> Case:
    return Case(
        id=case_id,
        name=case_id,
        risk_level="critical",
        turns=turns or ["hello"],
        rules=[rule],
        requires_tool_trace=requires_tool_trace,
    )


def config(tmp_path: Path) -> GateConfig:
    return GateConfig(
        sut=SutConfig(base_url="http://fake.invalid", start_mode="external"),
        run=RunConfig(
            cases_path=tmp_path / "cases",
            reports_dir=tmp_path / "reports",
            baselines_dir=tmp_path / "baselines",
        ),
        model=ModelConfig(execution_mode="deterministic", provider="deepseek"),
        trace=TraceConfig(persist_raw_snapshots=True, redact_pii=True, max_string_chars=4000),
    )


def run(cfg, cases, adapter, lifecycle, tmp_path):
    return asyncio.run(
        run_suite(
            cfg,
            cases,
            fail_on="critical",
            output=tmp_path / "reports" / "run",
            adapter=adapter,
            lifecycle=lifecycle,
        )
    )


def test_fake_adapter_runs_cases_serially_with_fresh_threads(tmp_path, monkeypatch):
    monkeypatch.setenv("GATE_SUT_REVISION", "rev-fake")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    tool_rule = Rule(id="R1", type="tool_must_be_called", severity="critical", params={"tool": "flight_status_tool"})
    never_rule = Rule(id="R2", type="tool_never_called", severity="critical", params={"tool": "cancel_flight"})
    cases = [
        case("CASE-A", rule=tool_rule, requires_tool_trace=True),
        case("CASE-B", rule=never_rule, turns=["hello again"]),
    ]
    adapter = FakeAdapter(
        [
            [turn_script(tool="flight_status_tool")],
            [turn_script()],
        ]
    )
    lifecycle = FakeLifecycle()

    report, json_path, markdown_path = run(config(tmp_path), cases, adapter, lifecycle, tmp_path)

    assert report["summary"]["passed"] == 2
    assert report["gate"]["status"] == "pass"
    assert report["gate"]["exit_code"] == 0
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert [session.thread_id for session in adapter.sessions] == ["thread-0", "thread-1"]
    assert adapter.send_inputs == ["hello", "hello again"]
    assert adapter.send_calls == 2
    assert adapter.closed_sessions == ["thread-0", "thread-1"]
    assert adapter.aclose_called is True
    assert lifecycle.started is True
    assert lifecycle.stopped is True

    traces = [item for item in report["cases"] if item["trace_path"]]
    assert len(traces) == 2
    assert all(Path(item["trace_path"]).is_file() for item in traces)


def test_protocol_error_becomes_case_error_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("GATE_SUT_REVISION", "rev-fake")
    rule = Rule(id="R1", type="tool_must_be_called", severity="critical", params={"tool": "flight_status_tool"})
    adapter = FakeAdapter([[turn_script(error=ProtocolError("boom"))]])
    lifecycle = FakeLifecycle()

    report, _, _ = run(config(tmp_path), [case("CASE-ERR", rule=rule)], adapter, lifecycle, tmp_path)

    assert report["cases"][0]["status"] == "error"
    assert report["cases"][0]["error_category"] == "protocol_error"
    assert report["gate"]["errors"] == 1
    assert report["gate"]["exit_code"] == 10
    assert adapter.send_calls == 1
    assert lifecycle.stopped is True


def test_incomplete_tool_trace_becomes_incomplete_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GATE_SUT_REVISION", "rev-fake")
    rule = Rule(id="R1", type="tool_must_be_called", severity="critical", params={"tool": "flight_status_tool"})
    adapter = FakeAdapter([[turn_script(tool="flight_status_tool", output=False)]])
    lifecycle = FakeLifecycle()

    report, _, _ = run(
        config(tmp_path),
        [case("CASE-INCOMPLETE", rule=rule, requires_tool_trace=True)],
        adapter,
        lifecycle,
        tmp_path,
    )

    assert report["cases"][0]["status"] == "incomplete"
    assert report["cases"][0]["assertions"][0]["passed"] is True
    assert report["summary"]["incomplete"] == 1
    assert report["gate"]["incomplete"] == 1
    assert report["gate"]["exit_code"] == 5


def test_lifecycle_failure_marks_all_cases_as_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("GATE_SUT_REVISION", "rev-fake")
    rule = Rule(id="R1", type="tool_must_be_called", severity="critical", params={"tool": "flight_status_tool"})
    adapter = FakeAdapter([[turn_script(tool="flight_status_tool")]])
    lifecycle = FakeLifecycle(fail=True)

    report, _, _ = run(config(tmp_path), [case("CASE-DOWN", rule=rule)], adapter, lifecycle, tmp_path)

    assert [item["status"] for item in report["cases"]] == ["error"]
    assert report["cases"][0]["error_category"] == "sut_unavailable"
    assert report["gate"]["errors"] == 1
    assert report["gate"]["exit_code"] == 10
    assert lifecycle.stopped is True
    assert adapter.aclose_called is True


def test_assertion_failure_sets_gate_exit_one(tmp_path, monkeypatch):
    monkeypatch.setenv("GATE_SUT_REVISION", "rev-fake")
    rule = Rule(id="R1", type="tool_never_called", severity="critical", params={"tool": "cancel_flight"})
    adapter = FakeAdapter([[turn_script(tool="cancel_flight")]])
    lifecycle = FakeLifecycle()

    report, _, _ = run(config(tmp_path), [case("CASE-FAIL", rule=rule)], adapter, lifecycle, tmp_path)

    assert report["cases"][0]["status"] == "fail"
    assert report["gate"]["critical_failures"] == 1
    assert report["gate"]["exit_code"] == 1
