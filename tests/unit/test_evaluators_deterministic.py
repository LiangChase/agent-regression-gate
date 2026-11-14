from __future__ import annotations

import pytest

from agent_regression_gate.evaluators.deterministic import evaluate_case

from tests.helpers import handoff, make_case, make_rule, make_trace, message, tool_call


def evaluate(rule, events, **trace_kwargs):
    return evaluate_case(make_case(rule), make_trace(events, **trace_kwargs))[0]


def test_tool_must_be_called_passes_and_fails():
    rule = make_rule("tool_must_be_called", tool="flight_status_tool")
    assert evaluate(rule, [tool_call("flight_status_tool")]).passed is True
    result = evaluate(rule, [tool_call("other_tool")])
    assert result.passed is False
    assert "flight_status_tool" in result.message


def test_tool_never_called_passes_and_fails():
    rule = make_rule("tool_never_called", tool="cancel_flight")
    assert evaluate(rule, [tool_call("other_tool")]).passed is True
    result = evaluate(rule, [tool_call("cancel_flight")])
    assert result.passed is False
    assert result.actual["count"] == 1


def test_tool_call_count_boundaries_allow_zero_when_only_max_is_set():
    rule = make_rule("tool_call_count", tool="cancel_flight", max=1)
    assert evaluate(rule, []).passed is True
    assert evaluate(rule, [tool_call("cancel_flight")]).passed is True
    assert evaluate(rule, [tool_call("cancel_flight"), tool_call("cancel_flight")]).passed is False


def test_tool_call_count_minimum_requires_calls():
    rule = make_rule("tool_call_count", tool="get_matching_flights", min=1, max=2)
    assert evaluate(rule, []).passed is False
    assert evaluate(rule, [tool_call("get_matching_flights")]).passed is True
    assert evaluate(rule, [tool_call("get_matching_flights")] * 3).passed is False


def test_tool_args_match_equals_required_and_nested_paths():
    rule = make_rule(
        "tool_args_match",
        tool="flight_status_tool",
        equals={"flight_number": "FLT-123", "meta.cabin": "economy"},
        required_fields=["flight_number"],
    )
    good = tool_call("flight_status_tool", {"flight_number": "FLT-123", "meta": {"cabin": "economy"}})
    assert evaluate(rule, [good]).passed is True

    wrong_value = tool_call("flight_status_tool", {"flight_number": "FLT-999", "meta": {"cabin": "economy"}})
    assert evaluate(rule, [wrong_value]).passed is False

    missing_field = tool_call("flight_status_tool", {"meta": {"cabin": "economy"}})
    assert evaluate(rule, [missing_field]).passed is False


def test_tool_args_match_requires_at_least_one_matching_call():
    rule = make_rule("tool_args_match", tool="flight_status_tool", required_fields=["flight_number"])
    result = evaluate(rule, [tool_call("other_tool")])
    assert result.passed is False
    assert result.actual["count"] == 0


def test_tool_args_match_regex_and_multiple_calls_must_all_pass():
    rule = make_rule("tool_args_match", tool="update_seat", matches={"seat": r"^\d{1,2}[A-F]$"})
    first = tool_call("update_seat", {"seat": "12A"})
    second = tool_call("update_seat", {"seat": "bad"})
    assert evaluate(rule, [first]).passed is True
    result = evaluate(rule, [first, second])
    assert result.passed is False
    assert "pattern_mismatch:seat" in result.actual["failures"]


def test_tool_order_is_a_subsequence_and_rejects_missing_or_reversed():
    rule = make_rule("tool_order", tools=["faq_lookup_tool", "issue_compensation"])

    assert evaluate(
        rule,
        [tool_call("faq_lookup_tool"), tool_call("issue_compensation")],
    ).passed is True

    assert evaluate(
        rule,
        [tool_call("get_trip_details"), tool_call("faq_lookup_tool"), tool_call("issue_compensation")],
    ).passed is True

    assert evaluate(
        rule,
        [tool_call("faq_lookup_tool"), tool_call("other_tool"), tool_call("issue_compensation")],
    ).passed is True

    assert evaluate(rule, [tool_call("get_trip_details"), tool_call("faq_lookup_tool")]).passed is False
    assert evaluate(rule, [tool_call("issue_compensation"), tool_call("faq_lookup_tool")]).passed is False


def test_tool_allowlisted_ignores_handoff_callbacks():
    rule = make_rule("tool_allowlisted")
    allowed = tool_call("book_new_flight", metadata={"gate_tool_allowlisted_for_agent": True})
    callback = tool_call("on_booking_handoff", metadata={"classification": "handoff_callback"})
    assert evaluate(rule, [allowed, callback]).passed is True

    unexpected = tool_call("export_all_passengers", metadata={"gate_tool_allowlisted_for_agent": False})
    result = evaluate(rule, [allowed, unexpected])
    assert result.passed is False
    assert result.actual[0]["tool"] == "export_all_passengers"


def test_handoff_required_matches_optional_target():
    any_handoff = make_rule("handoff_required")
    to_booking = make_rule("handoff_required", target="Booking and Cancellation Agent")

    events = [handoff("Booking and Cancellation Agent")]
    assert evaluate(any_handoff, events).passed is True
    assert evaluate(to_booking, events).passed is True
    assert evaluate(make_rule("handoff_required", target="Refunds and Compensation Agent"), events).passed is False


def test_final_response_contains_uses_last_message_and_is_case_insensitive():
    rule = make_rule("final_response_contains", text=["which", "confirmation", "flight"])
    events = [
        message("FIRST"),
        message("Which flight? Please provide your confirmation number."),
    ]
    assert evaluate(rule, events).passed is True
    assert evaluate(rule, [message("Please confirm.")]).passed is False


def test_final_response_contains_list_requires_all_terms():
    rule = make_rule("final_response_contains", text=["which", "confirmation", "flight"])
    assert evaluate(rule, [message("Which flight?")]).passed is False
    assert evaluate(rule, [message("Which flight? Please provide your confirmation number.")]).passed is True


def test_final_response_not_contains_is_case_insensitive():
    rule = make_rule("final_response_not_contains", text="success")
    assert evaluate(rule, [message("No success yet")]).passed is False
    assert evaluate(rule, [message("Please confirm")]).passed is True


def test_trace_complete_checks_capture_and_optional_tool_evidence():
    capture_only = make_rule("trace_complete")
    require_tools = make_rule("trace_complete", require_tool_trace=True)

    assert evaluate(capture_only, [], capture_status="complete", tool_trace_status="not_required").passed is True
    assert evaluate(capture_only, [], capture_status="incomplete", tool_trace_status="missing").passed is False
    assert evaluate(require_tools, [], capture_status="complete", tool_trace_status="missing").passed is False
    assert evaluate(require_tools, [], capture_status="complete", tool_trace_status="present").passed is True


def test_final_state_compares_nested_values():
    rule = make_rule("final_state", equals={"flight_number": "PA441", "meta.cabin": "economy"})
    context = {"flight_number": "PA441", "meta": {"cabin": "economy"}}
    assert evaluate(rule, [], final_context=context).passed is True
    assert evaluate(rule, [], final_context={"flight_number": "FLT-123"}).passed is False


def test_assertion_result_includes_evidence_ids():
    result = evaluate(
        make_rule("tool_must_be_called", tool="flight_status_tool"),
        [tool_call("flight_status_tool", event_id="evidence-1")],
    )
    assert result.evidence_event_ids == ["evidence-1"]
    assert result.severity == "critical"
