"""Baseline compatibility checks and case/assertion regression classification."""

from __future__ import annotations

from typing import Any

_COMPATIBILITY_KEYS = (
    "case_set_fingerprint",
    "trace_schema_version",
    "evaluator_version",
    "model",
)


def compare_reports(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compare two run reports without turning incomparable runs into regressions."""
    before_meta = baseline.get("comparison_context") or {}
    after_meta = current.get("comparison_context") or {}
    incompatible = []
    for key in _COMPATIBILITY_KEYS:
        old, new = before_meta.get(key), after_meta.get(key)
        if old != new:
            incompatible.append({"dimension": key, "baseline": old, "current": new})

    before = _case_assertions(baseline)
    after = _case_assertions(current)
    before_cases = {case.get("case_id"): case for case in baseline.get("cases", [])}
    after_cases = {case.get("case_id"): case for case in current.get("cases", [])}
    added_cases = sorted(set(after_cases) - set(before_cases))
    removed_cases = sorted(set(before_cases) - set(after_cases))
    case_status_changes = [
        {"case_id": case_id, "baseline": before_cases[case_id].get("status"), "current": after_cases[case_id].get("status")}
        for case_id in sorted(set(before_cases) & set(after_cases))
        if before_cases[case_id].get("status") != after_cases[case_id].get("status")
    ]
    new_failures, fixed, persistent, changed, missing_evidence = [], [], [], [], []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        item = {"case_id": key[0], "assertion_id": key[1]}
        if old is None:
            if new and not new.get("passed", False):
                new_failures.append({**item, "current": new})
            continue
        if new is None:
            current_case = after_cases.get(key[0], {})
            missing_evidence.append({
                **item,
                "baseline": old,
                "current_status": current_case.get("status"),
            })
            continue
        if old.get("passed", False) and not new.get("passed", False):
            new_failures.append({**item, "baseline": old, "current": new})
        elif not old.get("passed", False) and new.get("passed", False):
            fixed.append({**item, "baseline": old, "current": new})
        elif not old.get("passed", False) and not new.get("passed", False):
            persistent.append({**item, "baseline": old, "current": new})
        elif old.get("actual") != new.get("actual"):
            changed.append({**item, "baseline_actual": old.get("actual"), "current_actual": new.get("actual")})

    comparable = not incompatible
    return {
        "comparison_schema_version": 2,
        "baseline_run_id": baseline.get("run_id"),
        "current_run_id": current.get("run_id"),
        "baseline_sut_revision": baseline.get("sut_revision"),
        "current_sut_revision": current.get("sut_revision"),
        "comparable": comparable,
        "status": "comparable" if comparable else "not_comparable",
        "incompatibilities": incompatible,
        "new_failures": new_failures if comparable else [],
        "fixed": fixed if comparable else [],
        "persistent_failures": persistent if comparable else [],
        "changed_passes": changed if comparable else [],
        "missing_evidence": missing_evidence if comparable else [],
        "added_cases": added_cases,
        "removed_cases": removed_cases,
        "case_status_changes": case_status_changes if comparable else [],
        "summary": {
            "new_failures": len(new_failures) if comparable else 0,
            "fixed": len(fixed) if comparable else 0,
            "persistent_failures": len(persistent) if comparable else 0,
            "changed_passes": len(changed) if comparable else 0,
            "missing_evidence": len(missing_evidence) if comparable else 0,
            "added_cases": len(added_cases),
            "removed_cases": len(removed_cases),
            "case_status_changes": len(case_status_changes) if comparable else 0,
        },
    }


def _case_assertions(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    values = {}
    for case in report.get("cases", []):
        case_id = str(case.get("case_id", ""))
        for assertion in case.get("assertions", []):
            values[(case_id, str(assertion.get("assertion_id", "")))] = assertion
    return values


def render_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        "# 基线对比报告", "",
        f"- 基线运行：`{diff.get('baseline_run_id')}`",
        f"- 当前运行：`{diff.get('current_run_id')}`",
        f"- 对比状态：**{diff.get('status', 'unknown')}**", "",
    ]
    if diff.get("incompatibilities"):
        lines.extend(["## 不可比项", ""])
        for item in diff["incompatibilities"]:
            lines.append(f"- `{item['dimension']}` 发生变化：`{item.get('baseline')}` → `{item.get('current')}`")
        lines.append("")
    for title, key in (("新增失败", "new_failures"), ("已修复", "fixed"),
                       ("持续失败", "persistent_failures"), ("证据缺失", "missing_evidence"),
                       ("通过的断言结果变化", "changed_passes")):
        lines.extend([f"## {title}（{len(diff.get(key, []))}）", ""])
        if not diff.get(key):
            lines.append("无。")
        else:
            for item in diff[key]:
                lines.append(f"- `{item.get('case_id')}` / `{item.get('assertion_id')}`")
        lines.append("")
    lines.extend(["## 用例集变化", "", f"- 新增用例：{', '.join(diff.get('added_cases') or []) or '无'}",
                  f"- 移除用例：{', '.join(diff.get('removed_cases') or []) or '无'}", ""])
    return "\n".join(lines)
