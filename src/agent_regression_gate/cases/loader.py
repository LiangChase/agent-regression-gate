"""Load and validate YAML/JSON cases before a run starts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from ..errors import ConfigurationError
from .models import Case, CaseCollection, Rule

SUPPORTED_RULES = {
    "tool_must_be_called", "tool_never_called", "tool_call_count", "tool_args_match",
    "tool_order", "tool_allowlisted", "handoff_required", "final_response_contains",
    "final_response_not_contains", "trace_complete", "final_state",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SEVERITIES = {"critical", "high", "medium", "low", "warning", "info"}


def load_cases(path: str | Path) -> CaseCollection:
    root = Path(path)
    if not root.exists():
        raise ConfigurationError(f"Cases path '{root}' does not exist.")
    files = [root] if root.is_file() else sorted(
        [*root.rglob("*.yaml"), *root.rglob("*.yml"), *root.rglob("*.json")]
    )
    if not files:
        raise ConfigurationError(f"No YAML or JSON case files found under '{root}'.")
    cases: list[Case] = []
    seen: set[str] = set()
    for file in files:
        data = _read(file)
        items = data if isinstance(data, list) else [data]
        if not items:
            raise ConfigurationError(f"Case file '{file}' is empty.")
        for index, item in enumerate(items):
            for case in _parse_case(item, file, index):
                if case.id in seen:
                    raise ConfigurationError(f"Duplicate case id '{case.id}'.")
                seen.add(case.id)
                cases.append(case)
    return CaseCollection(cases=cases, source_files=[str(item) for item in files])


def _read(file: Path) -> Any:
    try:
        text = file.read_text(encoding="utf-8")
        value = json.loads(text) if file.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not parse case file '{file}'.") from exc
    if value is None:
        raise ConfigurationError(f"Case file '{file}' is empty.")
    return value


def _parse_case(value: Any, file: Path, index: int) -> list[Case]:
    label = f"{file} case[{index}]"
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be an object.")
    allowed = {"id", "version", "name", "risk_level", "tags", "description", "turns", "rules", "timeout_seconds", "parameters", "preconditions"}
    unknown = set(value) - allowed
    if unknown:
        raise ConfigurationError(f"{label} has unknown field(s): {', '.join(sorted(map(str, unknown)))}.")
    case_id = value.get("id")
    if not isinstance(case_id, str) or not _ID.fullmatch(case_id):
        raise ConfigurationError(f"{label} has an invalid or missing id.")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError(f"Case '{case_id}' requires a non-empty name.")
    risk = value.get("risk_level")
    if not isinstance(risk, str) or risk not in {"critical", "high", "medium", "low"}:
        raise ConfigurationError(f"Case '{case_id}' has an unsupported risk_level.")
    turns = value.get("turns")
    if isinstance(turns, str):
        turns = [turns]
    if not isinstance(turns, list) or not turns or any(not isinstance(t, str) or not t.strip() for t in turns):
        raise ConfigurationError(f"Case '{case_id}' requires one or more non-empty user turns.")
    raw_rules = value.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigurationError(f"Case '{case_id}' requires at least one rule.")
    timeout = value.get("timeout_seconds", 120)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 1800:
        raise ConfigurationError(f"Case '{case_id}' timeout_seconds must be between 1 and 1800.")
    tags = value.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ConfigurationError(f"Case '{case_id}' tags must be a list of non-empty strings.")
    preconditions = value.get("preconditions", [])
    if not isinstance(preconditions, list) or any(not isinstance(item, str) or not item.strip() for item in preconditions):
        raise ConfigurationError(f"Case '{case_id}' preconditions must be a list of non-empty descriptions.")
    parameters = value.get("parameters")
    parameter_sets = parameters if parameters is not None else [{}]
    if not isinstance(parameter_sets, list) or not parameter_sets or any(not isinstance(item, dict) for item in parameter_sets):
        raise ConfigurationError(f"Case '{case_id}' parameters must be a non-empty list of objects.")
    for parameter_values in parameter_sets:
        if any(not isinstance(key, str) or not isinstance(item, (str, int, float, bool, type(None))) for key, item in parameter_values.items()):
            raise ConfigurationError(f"Case '{case_id}' parameters must map string names to scalar values.")
    cases: list[Case] = []
    for parameter_index, parameter_values in enumerate(parameter_sets, start=1):
        suffix = f"-P{parameter_index:02d}" if parameters is not None else ""
        instance_id = case_id + suffix
        instance_turns = [_substitute(turn, parameter_values, case_id) for turn in turns]
        rules: list[Rule] = []
        for rule_index, raw_rule in enumerate(raw_rules):
            instance_rule = dict(raw_rule) if isinstance(raw_rule, dict) else raw_rule
            if isinstance(instance_rule, dict):
                instance_rule["id"] = f"{instance_rule.get('id', '')}{suffix}"
                instance_rule["params"] = _substitute(instance_rule.get("params", {}), parameter_values, case_id)
            rules.append(_parse_rule(instance_rule, instance_id, rule_index))
        rule_ids = [rule.id for rule in rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ConfigurationError(f"Case '{instance_id}' has duplicate rule ids.")
        cases.append(Case(
            id=instance_id, name=name.strip() + (f" [{parameter_index}]" if parameters is not None else ""),
            risk_level=risk, turns=instance_turns, rules=rules,
            version=str(value.get("version", "1")), tags=tags,
            description=str(value.get("description", "")), timeout_seconds=float(timeout),
            requires_tool_trace=any(
                r.type in {"tool_must_be_called", "tool_call_count", "tool_args_match", "tool_order"}
                or (r.type == "trace_complete" and bool(r.params.get("require_tool_trace")))
                for r in rules
            ),
            base_id=case_id, parameters=dict(parameter_values), preconditions=list(preconditions),
        ))
    return cases


def _substitute(value: Any, parameters: dict[str, Any], case_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _substitute(item, parameters, case_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, parameters, case_id) for item in value]
    if isinstance(value, str):
        pattern = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
        exact = pattern.fullmatch(value)
        if exact:
            key = exact.group(1)
            if key not in parameters:
                raise ConfigurationError(f"Case '{case_id}' references missing parameter '{key}'.")
            return parameters[key]
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in parameters:
                raise ConfigurationError(f"Case '{case_id}' references missing parameter '{key}'.")
            return str(parameters[key])
        return pattern.sub(replace, value)
    return value


def _parse_rule(value: Any, case_id: str, index: int) -> Rule:
    label = f"case '{case_id}' rule[{index}]"
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be an object.")
    allowed = {"id", "type", "severity", "params", "description"}
    unknown = set(value) - allowed
    if unknown:
        raise ConfigurationError(f"{label} has unknown field(s): {', '.join(sorted(map(str, unknown)))}.")
    rule_id = value.get("id")
    rule_type = value.get("type")
    severity = value.get("severity", "critical")
    params = value.get("params", {})
    if not isinstance(rule_id, str) or not _ID.fullmatch(rule_id):
        raise ConfigurationError(f"{label} has an invalid or missing id.")
    if not isinstance(rule_type, str) or rule_type not in SUPPORTED_RULES:
        raise ConfigurationError(f"{label} uses unknown evaluator '{rule_type}'.")
    if not isinstance(severity, str) or severity not in _SEVERITIES:
        raise ConfigurationError(f"{label} has unsupported severity '{severity}'.")
    if not isinstance(params, dict):
        raise ConfigurationError(f"{label} params must be an object.")
    _validate_rule_params(rule_type, params, label)
    return Rule(id=rule_id, type=rule_type, severity=severity, params=params,
                description=str(value.get("description", "")))


def _validate_rule_params(rule_type: str, params: dict[str, Any], label: str) -> None:
    required: dict[str, tuple[str, ...]] = {
        "tool_must_be_called": ("tool",), "tool_never_called": ("tool",),
        "tool_call_count": ("tool",), "tool_args_match": ("tool",),
        "tool_order": ("tools",), "handoff_required": (),
        "tool_allowlisted": (),
        "final_response_contains": ("text",), "final_response_not_contains": ("text",),
        "trace_complete": (), "final_state": ("equals",),
    }
    missing = [key for key in required[rule_type] if key not in params]
    if missing:
        raise ConfigurationError(f"{label} missing parameter(s): {', '.join(missing)}.")
    allowed_params = {
        "tool_must_be_called": {"tool"}, "tool_never_called": {"tool"},
        "tool_call_count": {"tool", "min", "max"},
        "tool_args_match": {"tool", "equals", "required_fields", "matches"},
        "tool_order": {"tools"}, "tool_allowlisted": set(), "handoff_required": {"target"},
        "final_response_contains": {"text"}, "final_response_not_contains": {"text"},
        "trace_complete": {"require_tool_trace"}, "final_state": {"equals"},
    }[rule_type]
    unknown = set(params) - allowed_params
    if unknown:
        raise ConfigurationError(f"{label} has unknown parameter(s): {', '.join(sorted(map(str, unknown)))}.")
    if "min" in params and (isinstance(params["min"], bool) or not isinstance(params["min"], int) or params["min"] < 0):
        raise ConfigurationError(f"{label} min must be a non-negative integer.")
    if "max" in params and (isinstance(params["max"], bool) or not isinstance(params["max"], int) or params["max"] < 0):
        raise ConfigurationError(f"{label} max must be a non-negative integer.")
    if "min" in params and "max" in params and params["min"] > params["max"]:
        raise ConfigurationError(f"{label} min cannot exceed max.")
    for key in ("tool", "target"):
        if key in params and not isinstance(params[key], str):
            raise ConfigurationError(f"{label} {key} must be a string.")
    if rule_type == "tool_order" and (
        not isinstance(params["tools"], list) or len(params["tools"]) < 2
        or any(not isinstance(tool, str) or not tool for tool in params["tools"])
    ):
        raise ConfigurationError(f"{label} tools must contain at least two non-empty names.")
    if rule_type == "tool_args_match":
        if not any(key in params for key in ("equals", "required_fields", "matches")):
            raise ConfigurationError(f"{label} requires equals, required_fields, or matches constraints.")
        for key in ("equals", "matches"):
            if key in params and not isinstance(params[key], dict):
                raise ConfigurationError(f"{label} {key} must be an object.")
            if key in params and any(not isinstance(path, str) or not path for path in params[key]):
                raise ConfigurationError(f"{label} {key} keys must be non-empty field paths.")
        if "required_fields" in params and (
            not isinstance(params["required_fields"], list)
            or any(not isinstance(item, str) or not item for item in params["required_fields"])
        ):
            raise ConfigurationError(f"{label} required_fields must be a list of field paths.")
        for pattern in params.get("matches", {}).values():
            if not isinstance(pattern, str):
                raise ConfigurationError(f"{label} regex constraints must be strings.")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigurationError(f"{label} contains an invalid regex constraint.") from exc
    if rule_type in {"final_response_contains", "final_response_not_contains"}:
        text = params["text"]
        if not (isinstance(text, str) and text) and not (
            isinstance(text, list) and text and all(isinstance(item, str) and item for item in text)
        ):
            raise ConfigurationError(f"{label} text must be a non-empty string or string list.")
    if rule_type == "final_state" and not isinstance(params["equals"], dict):
        raise ConfigurationError(f"{label} equals must be an object of expected context values.")
    if rule_type == "final_state" and any(not isinstance(path, str) or not path for path in params["equals"]):
        raise ConfigurationError(f"{label} final_state keys must be non-empty field paths.")
    if rule_type == "trace_complete" and "require_tool_trace" in params and not isinstance(params["require_tool_trace"], bool):
        raise ConfigurationError(f"{label} require_tool_trace must be true or false.")

