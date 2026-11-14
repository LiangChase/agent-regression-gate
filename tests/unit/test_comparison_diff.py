from __future__ import annotations

import pytest

from agent_regression_gate.comparison.diff import compare_reports, render_diff_markdown

MODEL = {"provider": "deepseek", "model_name": "deepseek-flash", "execution_mode": "deterministic"}


def assertion(assertion_id: str, passed: bool, actual=None):
    return {
        "assertion_id": assertion_id,
        "name": "rule",
        "passed": passed,
        "severity": "critical",
        "expected": {},
        "actual": actual or {},
        "evidence_event_ids": ["event-1"],
        "message": "ok" if passed else "failed",
    }


def case(case_id: str, status: str, assertions: list[dict]):
    return {"case_id": case_id, "status": status, "assertions": assertions}


def report(
    run_id: str,
    cases: list[dict],
    *,
    fingerprint: str = "fingerprint-1",
    evaluator: str = "deterministic-v3",
    model: dict | None = None,
    sut: str = "rev-1",
):
    return {
        "run_id": run_id,
        "sut_revision": sut,
        "comparison_context": {
            "case_set_fingerprint": fingerprint,
            "trace_schema_version": 1,
            "evaluator_version": evaluator,
            "model": model or MODEL,
        },
        "cases": cases,
    }


def test_classifies_new_fixed_persistent_and_changed_passes():
    baseline = report(
        "baseline",
        [
            case(
                "CASE-1",
                "fail",
                [
                    assertion("R-NEW", True, {"value": 1}),
                    assertion("R-FIXED", False),
                    assertion("R-PERSISTENT", False),
                    assertion("R-CHANGED", True, {"value": "old"}),
                ],
            )
        ],
    )
    current = report(
        "current",
        [
            case(
                "CASE-1",
                "fail",
                [
                    assertion("R-NEW", False),
                    assertion("R-FIXED", True),
                    assertion("R-PERSISTENT", False),
                    assertion("R-CHANGED", True, {"value": "new"}),
                ],
            )
        ],
    )
    diff = compare_reports(baseline, current)
    assert diff["status"] == "comparable"
    assert [item["assertion_id"] for item in diff["new_failures"]] == ["R-NEW"]
    assert [item["assertion_id"] for item in diff["fixed"]] == ["R-FIXED"]
    assert [item["assertion_id"] for item in diff["persistent_failures"]] == ["R-PERSISTENT"]
    assert [item["assertion_id"] for item in diff["changed_passes"]] == ["R-CHANGED"]
    assert diff["summary"] == {
        "new_failures": 1,
        "fixed": 1,
        "persistent_failures": 1,
        "changed_passes": 1,
        "added_cases": 0,
        "removed_cases": 0,
        "case_status_changes": 0,
    }


def test_reports_added_and_removed_cases():
    baseline = report("baseline", [case("CASE-OLD", "pass", [assertion("R1", True)])])
    current = report("current", [case("CASE-NEW", "pass", [assertion("R1", True)])])
    diff = compare_reports(baseline, current)
    assert diff["added_cases"] == ["CASE-NEW"]
    assert diff["removed_cases"] == ["CASE-OLD"]


def test_incompatible_context_suppresses_assertion_differences():
    baseline = report("baseline", [case("CASE-1", "pass", [assertion("R1", True)])])
    current = report(
        "current",
        [case("CASE-1", "fail", [assertion("R1", False)])],
        model={"provider": "deepseek", "model_name": "another-model", "execution_mode": "deterministic"},
    )
    diff = compare_reports(baseline, current)
    assert diff["status"] == "not_comparable"
    assert diff["comparable"] is False
    assert diff["new_failures"] == []
    assert {item["dimension"] for item in diff["incompatibilities"]} == {"model"}


def test_changed_evaluator_version_is_not_comparable():
    baseline = report("baseline", [], evaluator="deterministic-v2")
    current = report("current", [], evaluator="deterministic-v3")
    diff = compare_reports(baseline, current)
    assert diff["status"] == "not_comparable"
    assert diff["incompatibilities"][0]["dimension"] == "evaluator_version"


@pytest.mark.xfail(
    strict=True,
    reason="Known defect: an assertion missing from an incomplete/error run is classified as fixed.",
)
def test_missing_assertion_is_not_reported_as_fixed():
    baseline = report("baseline", [case("CASE-1", "fail", [assertion("R1", False)])])
    current = report("current", [case("CASE-1", "error", [])])
    diff = compare_reports(baseline, current)
    assert diff["fixed"] == []


def test_render_markdown_uses_chinese_labels_and_stable_ids():
    baseline = report("baseline", [case("CASE-1", "pass", [assertion("R1", True)])])
    current = report("current", [case("CASE-1", "fail", [assertion("R1", False)])])
    markdown = render_diff_markdown(compare_reports(baseline, current))
    assert "# 基线对比报告" in markdown
    assert "## 新增失败（1）" in markdown
    assert "`CASE-1` / `R1`" in markdown
    assert "## 用例集变化" in markdown
