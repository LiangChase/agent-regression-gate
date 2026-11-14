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


def evaluate(reports, expected_runs=3):
    module = load_script()
    return module.evaluate(reports, expected_runs=expected_runs, fail_threshold=2)


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


def test_live_workflow_contract():
    document = yaml.safe_load(LIVE_WORKFLOW.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))
    assert "workflow_call" in triggers
    assert triggers["workflow_call"]["secrets"]["DEEPSEEK_API_KEY"]["required"] is True
    job = document["jobs"]["live-sut-gate"]
    assert job["name"] == "live-sut-gate"
    run_steps = [step for step in job["steps"] if step.get("name") == "Run live samples"]
    assert run_steps
    command = json.dumps(run_steps[0]["run"], ensure_ascii=False)
    for case_id in ("AIR-01", "AIR-03", "AIR-05", "AIR-10", "AIR-15"):
        assert case_id in command
    assert "AIR-07" not in command
    assert "evaluate_live_samples.py" in json.dumps(job, ensure_ascii=False)


def test_release_workflow_requires_live_gate():
    document = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert document["jobs"]["live-sut-gate"]["uses"].endswith("live-sut-gate.yml")
    assert document["jobs"]["release"]["needs"] == "live-sut-gate"
