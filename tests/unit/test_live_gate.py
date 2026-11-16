from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "evaluate_live_samples.py"
LIVE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-sut-gate.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def load_script():
    spec = importlib.util.spec_from_file_location("evaluate_live_samples", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_report(
    run_id: str,
    *,
    critical_passed: list[bool],
    high_passed: bool = True,
    case_status: str = "pass",
    gate_errors: int = 0,
    gate_incomplete: int = 0,
) -> dict:
    assertions = [
        {
            "assertion_id": f"R{index}",
            "severity": "critical",
            "passed": passed,
        }
        for index, passed in enumerate(critical_passed, start=1)
    ]
    if high_passed is not None:
        assertions.append({"assertion_id": "HIGH", "severity": "high", "passed": high_passed})
    return {
        "run_id": run_id,
        "gate": {"errors": gate_errors, "incomplete": gate_incomplete},
        "cases": [
            {
                "case_id": "CASE-1",
                "status": case_status,
                "error_message": None,
                "assertions": assertions,
            }
        ],
    }


def evaluate(reports, expected_runs=3, expected_cases=None):
    module = load_script()
    return module.evaluate(
        reports,
        expected_runs=expected_runs,
        fail_threshold=2,
        expected_cases=expected_cases,
    )


def test_all_samples_pass():
    result = evaluate([make_report(str(i), critical_passed=[True]) for i in range(3)])
    assert result["status"] == "pass"
    assert result["exit_code"] == 0
    assert result["summary"]["regressions"] == 0


def test_two_of_three_critical_failures_is_regression():
    result = evaluate(
        [
            make_report("1", critical_passed=[False]),
            make_report("2", critical_passed=[False]),
            make_report("3", critical_passed=[True]),
        ]
    )
    assert result["status"] == "regression"
    assert result["exit_code"] == 1
    assert result["regressions"][0]["assertion_id"] == "R1"


def test_one_of_three_critical_failures_is_flaky_and_blocks_release():
    result = evaluate(
        [
            make_report("1", critical_passed=[True]),
            make_report("2", critical_passed=[False]),
            make_report("3", critical_passed=[True]),
        ]
    )
    assert result["status"] == "flaky"
    assert result["exit_code"] == 1
    assert result["flaky"][0]["assertion_id"] == "R1"


def test_non_critical_failures_are_advisory_only():
    result = evaluate(
        [
            make_report("1", critical_passed=[True], high_passed=False),
            make_report("2", critical_passed=[True], high_passed=False),
            make_report("3", critical_passed=[True], high_passed=False),
        ]
    )
    assert result["status"] == "pass"
    assert result["exit_code"] == 0
    assert result["summary"]["advisory"] == 1


def test_missing_report_is_invalid():
    result = evaluate([make_report("1", critical_passed=[True])], expected_runs=3)
    assert result["status"] == "invalid"
    assert result["exit_code"] == 2
    assert result["infra_errors"][0]["reason"] == "missing_reports"


def test_case_error_or_incomplete_is_invalid():
    error_result = evaluate(
        [
            make_report("1", critical_passed=[True], case_status="error"),
            make_report("2", critical_passed=[True]),
            make_report("3", critical_passed=[True]),
        ]
    )
    assert error_result["status"] == "invalid"
    assert any(item.get("reason") == "case_error" for item in error_result["infra_errors"])

    gate_error = evaluate(
        [
            make_report("1", critical_passed=[True], gate_errors=1),
            make_report("2", critical_passed=[True]),
            make_report("3", critical_passed=[True]),
        ]
    )
    assert gate_error["status"] == "invalid"


def test_missing_expected_case_is_invalid():
    result = evaluate(
        [make_report(str(i), critical_passed=[True]) for i in range(3)],
        expected_cases={"CASE-1", "CASE-2"},
    )
    assert result["status"] == "invalid"
    assert result["exit_code"] == 2
    assert result["coverage"]["expected_cases"] == ["CASE-1", "CASE-2"]
    assert result["coverage"]["observed_cases"] == ["CASE-1"]
    assert result["coverage"]["missing_cases"] == ["CASE-2"]
    assert any(item.get("reason") == "missing_case" for item in result["infra_errors"])


def test_present_expected_cases_keep_the_gate_green():
    result = evaluate(
        [make_report(str(i), critical_passed=[True]) for i in range(3)],
        expected_cases={"CASE-1"},
    )
    assert result["status"] == "pass"
    assert result["coverage"]["missing_cases"] == []


def test_live_workflow_is_manual_and_lock_triggered():
    document = yaml.safe_load(LIVE_WORKFLOW.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers
    assert "workflow_call" not in triggers
    # A path-filtered workflow cannot be a reliable required check: unrelated
    # PRs would stay pending. The workflow must run everywhere and select
    # internally.
    pull_request = triggers.get("pull_request") or {}
    assert not pull_request.get("paths")

    job = document["jobs"]["live-sut-gate"]
    assert job["name"] == "live-sut-gate"
    steps = job["steps"]
    scope = next(step for step in steps if step.get("name") == "Decide whether the live gate applies")
    assert scope["id"] == "scope"
    assert "config/sut.lock.yaml" in scope["run"]
    assert "workflow_dispatch" in scope["run"]

    live_steps = [
        step
        for step in steps
        if step.get("name")
        in {
            "Read pinned SUT revision",
            "Checkout pinned SUT",
            "Set up Python",
            "Set up uv",
            "Require the DeepSeek secret",
            "Install Gate dependencies",
            "Install SUT dependencies in an isolated venv",
            "Start the pinned SUT",
            "Run live samples",
            "Evaluate live samples",
            "Write job summary",
            "Upload live gate evidence",
            "Stop the SUT",
        }
    ]
    assert len(live_steps) == 13
    for step in live_steps:
        assert "steps.scope.outputs.run_live == 'true'" in step.get("if", "")

    run_steps = [step for step in steps if step.get("name") == "Run live samples"]
    assert run_steps
    command = json.dumps(run_steps[0]["run"], ensure_ascii=False)
    # The workflow selects by risk so new critical cases are covered without
    # maintaining a second hard-coded list.
    assert "--risk critical" in command
    assert "--exclude-case AIR-07" in command
    assert "--case" not in command

    evaluate_steps = [step for step in steps if step.get("name") == "Evaluate live samples"]
    assert evaluate_steps
    evaluation = json.dumps(evaluate_steps[0]["run"], ensure_ascii=False)
    assert "--cases-path cases/airline" in evaluation
    assert "--risk critical" in evaluation
    assert "--exclude-case AIR-07" in evaluation
    assert "evaluate_live_samples.py" in evaluation


def test_live_selection_covers_all_non_flaky_critical_cases():
    from agent_regression_gate.cases.loader import load_cases
    from agent_regression_gate.cli import _select_cases

    collection = load_cases(REPO_ROOT / "cases" / "airline")
    critical = {case.id for case in collection.cases if case.risk_level == "critical"}
    assert critical == {
        "AIR-01",
        "AIR-02-P01",
        "AIR-02-P02",
        "AIR-03",
        "AIR-04",
        "AIR-05",
        "AIR-06",
        "AIR-07",
        "AIR-10",
        "AIR-11",
        "AIR-13",
        "AIR-14",
        "AIR-15",
    }
    assert len(critical) == 13

    selected = _select_cases(
        collection.cases,
        case_ids=None,
        tags=None,
        risks=["critical"],
        exclude_case_ids=["AIR-07"],
    )
    selected_ids = {case.id for case in selected}
    assert selected_ids == critical - {"AIR-07"}
    assert len(selected_ids) == 12


def test_release_concept_is_not_part_of_the_gate():
    assert not RELEASE_WORKFLOW.exists()
