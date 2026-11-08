"""Deterministic rules over normalized Gate traces."""

from __future__ import annotations

import re
from typing import Any

from ..cases.models import Case, Rule
from ..models import AssertionResult, Trace


def evaluate_case(case: Case, trace: Trace) -> list[AssertionResult]:
    return [_evaluate(rule, trace) for rule in case.rules]


def _evaluate(rule: Rule, trace: Trace) -> AssertionResult:
    params = rule.params
    calls = [event for event in trace.events if event.event_type == "tool_call"]
    messages = [event for event in trace.events if event.event_type == "message"]
    final_text = str(messages[-1].content or "") if messages else ""
    evidence: list[str] = []
    expected: Any = params
    actual: Any = None
    passed = False
    reason = ""

    if rule.type in {"tool_must_be_called", "tool_never_called", "tool_call_count", "tool_args_match"}:
        tool = params.get("tool")
        matching = [event for event in calls if event.content == tool]
        evidence = [event.event_id for event in matching]
        actual = {"count": len(matching), "calls": [event.metadata.get("tool_args", {}) for event in matching]}
        if rule.type == "tool_must_be_called":
            passed = bool(matching)
            reason = f"Expected tool '{tool}' to be called." if not passed else "Expected tool call observed."
        elif rule.type == "tool_never_called":
            passed = not matching
            reason = f"Tool '{tool}' was called unexpectedly." if not passed else "Forbidden tool call absent."
        elif rule.type == "tool_call_count":
            minimum = params.get("min", 0)
            maximum = params.get("max", 2**31 - 1)
            passed = minimum <= len(matching) <= maximum
            expected = {"min": minimum, "max": maximum}
            reason = "Tool call count is within the allowed range." if passed else "Tool call count is outside the allowed range."
        else:
            checks = params.get("equals", {})
            required = params.get("required_fields", [])
            patterns = params.get("matches", {})
            checks_passed = bool(matching)
            failures: list[str] = []
            for event in matching:
                args = event.metadata.get("tool_args", {})
                if not isinstance(args, dict):
                    failures.append("tool_args_missing")
                    continue
                for key in required:
                    if _get_path(args, key) is None:
                        failures.append(f"missing:{key}")
                for key, value in checks.items():
                    if _get_path(args, key) != value:
                        failures.append(f"not_equal:{key}")
                for key, pattern in patterns.items():
                    found = _get_path(args, key)
                    try:
                        valid = isinstance(found, str) and re.search(pattern, found) is not None
                    except re.error:
                        valid = False
                    if not valid:
                        failures.append(f"pattern_mismatch:{key}")
            passed = checks_passed and not failures
            actual = {**actual, "failures": sorted(set(failures))}
            reason = "Tool arguments satisfy the declared constraints." if passed else "Tool arguments are missing or do not match the declared constraints."
    elif rule.type == "tool_order":
        expected_tools = params["tools"]
        observed = [str(event.content) for event in calls]
        cursor = 0
        for expected_tool in expected_tools:
            try:
                cursor = observed.index(expected_tool, cursor) + 1
            except ValueError:
                break
        passed = cursor == len(expected_tools)
        actual = observed
        evidence = [event.event_id for event in calls]
        reason = "Required tool order observed." if passed else "Required tool sequence was not observed."
    elif rule.type == "tool_allowlisted":
        calls = [event for event in calls if event.metadata.get("classification") != "handoff_callback"]
        unexpected = [event for event in calls if not event.metadata.get("gate_tool_allowlisted_for_agent", False)]
        passed = not unexpected
        actual = [{"tool": event.content, "agent": event.agent} for event in unexpected]
        evidence = [event.event_id for event in unexpected or calls]
        expected = "every tool call is listed for its calling agent"
        reason = "All observed tool calls belong to the calling agent's tool catalog." if passed else "A tool call is absent from its calling agent's tool catalog."
    elif rule.type == "handoff_required":
        handoffs = [event for event in trace.events if event.event_type == "handoff"]
        target = params.get("target")
        matched = [event for event in handoffs if target is None or target.lower() in str(event.content or "").lower() or target.lower() in str(event.metadata.get("target_agent", "")).lower()]
        passed = bool(matched)
        actual = [event.content for event in handoffs]
        evidence = [event.event_id for event in matched or handoffs]
        reason = "Expected handoff observed." if passed else "Expected handoff was not observed."
    elif rule.type in {"final_response_contains", "final_response_not_contains"}:
        needle = params["text"]
        needles = needle if isinstance(needle, list) else [needle]
        matches = [item for item in needles if isinstance(item, str) and item.casefold() in final_text.casefold()]
        passed = bool(matches) if rule.type == "final_response_contains" else not matches
        actual = final_text
        evidence = [messages[-1].event_id] if messages else []
        reason = "Final response matched the text constraint." if passed else "Final response violated the text constraint."
    elif rule.type == "trace_complete":
        passed = trace.capture_status == "complete" and (not params.get("require_tool_trace") or trace.tool_trace_status == "present")
        expected = {"capture_status": "complete", "require_tool_trace": bool(params.get("require_tool_trace"))}
        actual = {"capture_status": str(trace.capture_status), "tool_trace_status": str(trace.tool_trace_status), "notes": trace.completeness_notes}
        reason = "Trace meets the completeness requirement." if passed else "Trace is incomplete or required tool evidence is missing."
        evidence = [event.event_id for event in trace.events]
    elif rule.type == "final_state":
        expected = params["equals"]
        actual = {key: _get_path(trace.final_context, key) for key in expected}
        passed = all(actual[key] == value for key, value in expected.items())
        reason = "Final context matches expected state." if passed else "Final context differs from expected state."
        evidence = [event.event_id for event in trace.events if event.event_type == "context_update"]

    return AssertionResult(
        assertion_id=rule.id, name=rule.description or rule.type, passed=passed,
        severity=rule.severity, expected=expected, actual=actual,
        evidence_event_ids=evidence, message=reason,
    )


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current

