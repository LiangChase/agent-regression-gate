from __future__ import annotations

import pytest
import yaml

from agent_regression_gate.cases import load_cases
from agent_regression_gate.errors import ConfigurationError


def write_cases(tmp_path, cases):
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(cases, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_cases(tmp_path)


def case_with_rule(rule: dict, *, case_id: str = "CASE-1") -> dict:
    return {
        "id": case_id,
        "version": "1",
        "name": "example",
        "risk_level": "critical",
        "turns": ["hello"],
        "rules": [{"id": "R1", "severity": "critical", **rule}],
    }


def test_parameter_expansion_preserves_base_id(tmp_path):
    collection = write_cases(
        tmp_path,
        [
            {
                "id": "CASE-PARAM",
                "version": "1",
                "name": "parameterized",
                "risk_level": "critical",
                "turns": ["check {{ flight }}"],
                "parameters": [{"flight": "AA1"}, {"flight": "BB2"}],
                "rules": [
                    {
                        "id": "R1",
                        "type": "tool_args_match",
                        "severity": "critical",
                        "params": {"tool": "t", "equals": {"flight": "{{ flight }}"}},
                    }
                ],
            }
        ],
    )
    assert [case.id for case in collection.cases] == ["CASE-PARAM-P01", "CASE-PARAM-P02"]
    assert all(case.base_id == "CASE-PARAM" for case in collection.cases)
    assert collection.cases[0].turns == ["check AA1"]
    assert collection.cases[0].parameters == {"flight": "AA1"}


@pytest.mark.parametrize(
    "rule",
    [
        {"type": "tool_must_be_called", "params": {"tool": "t"}},
        {"type": "tool_args_match", "params": {"tool": "t", "equals": {"x": 1}}},
        {"type": "tool_order", "params": {"tools": ["a", "b"]}},
    ],
)
def test_rules_that_require_evidence_set_requires_tool_trace(tmp_path, rule):
    collection = write_cases(tmp_path, [case_with_rule(rule)])
    assert collection.cases[0].requires_tool_trace is True


def test_tool_call_count_with_only_max_does_not_require_tool_trace(tmp_path):
    collection = write_cases(
        tmp_path,
        [case_with_rule({"type": "tool_call_count", "params": {"tool": "cancel_flight", "max": 1}})],
    )
    assert collection.cases[0].requires_tool_trace is False


def test_tool_call_count_with_min_one_requires_tool_trace(tmp_path):
    collection = write_cases(
        tmp_path,
        [case_with_rule({"type": "tool_call_count", "params": {"tool": "cancel_flight", "min": 1}})],
    )
    assert collection.cases[0].requires_tool_trace is True


def test_trace_complete_controls_evidence_requirement(tmp_path):
    collection = write_cases(
        tmp_path,
        [
            case_with_rule({"type": "trace_complete", "params": {"require_tool_trace": True}}, case_id="REQ"),
            case_with_rule({"type": "trace_complete", "params": {"require_tool_trace": False}}, case_id="OPT"),
        ],
    )
    by_id = {case.id: case for case in collection.cases}
    assert by_id["REQ"].requires_tool_trace is True
    assert by_id["OPT"].requires_tool_trace is False


def test_tool_never_called_and_allowlist_do_not_require_tool_trace(tmp_path):
    collection = write_cases(
        tmp_path,
        [
            case_with_rule({"type": "tool_never_called", "params": {"tool": "t"}}, case_id="NEVER"),
            case_with_rule({"type": "tool_allowlisted", "params": {}}, case_id="ALLOW"),
        ],
    )
    by_id = {case.id: case for case in collection.cases}
    assert by_id["NEVER"].requires_tool_trace is False
    assert by_id["ALLOW"].requires_tool_trace is False


def test_duplicate_rule_ids_are_rejected(tmp_path):
    case = case_with_rule({"type": "tool_must_be_called", "params": {"tool": "a"}})
    case["rules"].append({"id": "R1", "type": "tool_must_be_called", "severity": "critical", "params": {"tool": "b"}})
    with pytest.raises(ConfigurationError, match="duplicate rule ids"):
        write_cases(tmp_path, [case])


def test_unknown_rule_type_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="unknown"):
        write_cases(tmp_path, [case_with_rule({"type": "not_a_rule", "params": {}})])


def test_unknown_case_field_is_rejected(tmp_path):
    case = case_with_rule({"type": "tool_must_be_called", "params": {"tool": "a"}})
    case["unexpected"] = True
    with pytest.raises(ConfigurationError, match="unknown"):
        write_cases(tmp_path, [case])


@pytest.mark.parametrize(
    "params",
    [
        {"tool": "a", "min": 2, "max": 1},
        {"tool": "a", "min": -1},
        {"tool": "a", "min": True},
        {"tool": "a", "unknown": 1},
    ],
)
def test_invalid_tool_call_count_params_are_rejected(tmp_path, params):
    with pytest.raises(ConfigurationError):
        write_cases(tmp_path, [case_with_rule({"type": "tool_call_count", "params": params})])
