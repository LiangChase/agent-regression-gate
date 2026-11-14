from __future__ import annotations

from dataclasses import replace

import yaml

from agent_regression_gate.cases import load_cases
from agent_regression_gate.config import load_config
from agent_regression_gate.execution.runner import (
    _comparison_context,
    _gate,
    _model_name,
    _sut_revision,
    _summary,
)


def case_doc(status: str, *assertions: tuple[bool, str]):
    return {
        "case_id": "CASE-1",
        "status": status,
        "assertions": [
            {"passed": passed, "severity": severity}
            for passed, severity in assertions
        ],
    }


def test_gate_blocks_critical_assertions_by_default():
    gate = _gate([case_doc("fail", (False, "critical"))], "critical")
    assert gate["status"] == "fail"
    assert gate["critical_failures"] == 1
    assert gate["blocking_assertions"] == 1
    assert gate["exit_code"] == 1


def test_gate_does_not_block_high_assertions_under_critical_policy():
    gate = _gate([case_doc("fail", (False, "high"))], "critical")
    assert gate["status"] == "pass"
    assert gate["critical_failures"] == 0
    assert gate["blocking_assertions"] == 0
    assert gate["exit_code"] == 0


def test_gate_blocks_high_assertions_when_policy_is_high():
    gate = _gate([case_doc("fail", (False, "high"))], "high")
    assert gate["status"] == "fail"
    assert gate["blocking_assertions"] == 1
    assert gate["exit_code"] == 1


def test_gate_always_blocks_infrastructure_errors_and_incomplete_traces():
    error_gate = _gate([case_doc("error")], "critical")
    assert error_gate["errors"] == 1
    assert error_gate["exit_code"] == 10

    incomplete_gate = _gate([case_doc("incomplete")], "critical")
    assert incomplete_gate["incomplete"] == 1
    assert incomplete_gate["exit_code"] == 5

    infra_gate = _gate([case_doc("pass")], "critical", infra_error="lifecycle failed")
    assert infra_gate["errors"] == 1
    assert infra_gate["exit_code"] == 10


def test_summary_counts_case_statuses_and_assertions():
    summary = _summary(
        [
            case_doc("pass", (True, "critical")),
            case_doc("fail", (False, "critical"), (True, "high")),
            case_doc("error"),
            case_doc("incomplete", (False, "critical")),
        ]
    )
    assert summary == {
        "case_count": 4,
        "passed": 1,
        "failed": 1,
        "errors": 1,
        "incomplete": 1,
        "assertion_count": 4,
    }


def test_comparison_context_is_stable_and_tracks_turns_not_names(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    config = load_config("config/gate.example.yaml", require_model_credentials=False)
    cases = load_cases("cases/airline").cases
    context = _comparison_context(cases, "rev-1", config)

    assert context["evaluator_version"] == "deterministic-v4"
    assert context["trace_schema_version"] == 1
    assert context["sut_revision"] == "rev-1"
    assert context["model"]["model_name"] == "deepseek-flash"
    assert len(context["case_set_fingerprint"]) == 64

    renamed = [replace(case, name="renamed") for case in cases]
    assert _comparison_context(renamed, "rev-1", config)["case_set_fingerprint"] == context["case_set_fingerprint"]

    changed_turn = [replace(case, turns=["different input"]) for case in cases]
    assert _comparison_context(changed_turn, "rev-1", config)["case_set_fingerprint"] != context["case_set_fingerprint"]


def test_sut_revision_prefers_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("GATE_SUT_REVISION", "env-rev")
    monkeypatch.chdir(tmp_path)
    assert _sut_revision() == "env-rev"


def test_sut_revision_falls_back_to_lock_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GATE_SUT_REVISION", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sut.lock.yaml").write_text(
        yaml.safe_dump({"sut": {"revision": "locked-rev"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert _sut_revision() == "locked-rev"


def test_sut_revision_returns_none_without_lock(monkeypatch, tmp_path):
    monkeypatch.delenv("GATE_SUT_REVISION", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _sut_revision() is None


def test_model_name_uses_provider_specific_environment(monkeypatch):
    config = load_config("config/gate.example.yaml", require_model_credentials=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-test")
    assert _model_name(config) == "deepseek-test"
