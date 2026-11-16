"""Aggregate repeated live SUT runs and classify regressions vs flaky failures.

The release gate runs the same critical cases several times. A critical
assertion that fails in at least `--fail-threshold` runs is a regression; a
critical assertion that fails fewer times is flaky. Both block the release.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_report(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def evaluate(
    reports: list[dict[str, Any] | None],
    *,
    expected_runs: int,
    fail_threshold: int,
    expected_cases: set[str] | None = None,
) -> dict[str, Any]:
    samples: dict[tuple[str, str], list[bool]] = defaultdict(list)
    severities: dict[tuple[str, str], str] = {}
    infra_errors: list[dict[str, Any]] = []
    expected = set(expected_cases or set())
    observed_cases: set[str] = set()

    if len(reports) < expected_runs:
        infra_errors.append(
            {
                "reason": "missing_reports",
                "expected": expected_runs,
                "received": len(reports),
            }
        )

    for index, report in enumerate(reports, start=1):
        if report is None:
            infra_errors.append({"sample": index, "reason": "report_unavailable"})
            continue
        gate = report.get("gate") or {}
        if gate.get("errors") or gate.get("incomplete"):
            infra_errors.append(
                {
                    "sample": index,
                    "reason": "gate_error_or_incomplete",
                    "run_id": report.get("run_id"),
                    "errors": gate.get("errors", 0),
                    "incomplete": gate.get("incomplete", 0),
                }
            )
        seen_cases: set[str] = set()
        for case in report.get("cases", []) or []:
            case_id = str(case.get("case_id", ""))
            seen_cases.add(case_id)
            observed_cases.add(case_id)
            case_status = case.get("status")
            if case_status in {"error", "incomplete"}:
                infra_errors.append(
                    {
                        "sample": index,
                        "reason": f"case_{case_status}",
                        "case_id": case_id,
                        "error": case.get("error_message"),
                    }
                )
            for assertion in case.get("assertions", []) or []:
                assertion_id = str(assertion.get("assertion_id", ""))
                key = (case_id, assertion_id)
                severities[key] = str(assertion.get("severity", "critical"))
                samples[key].append(bool(assertion.get("passed", False)))
        for case_id in sorted(expected - seen_cases):
            infra_errors.append(
                {
                    "sample": index,
                    "reason": "missing_case",
                    "case_id": case_id,
                }
            )

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    flaky: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []

    all_keys = sorted(set(samples) | set(severities))
    for key in all_keys:
        case_id, assertion_id = key
        values = samples.get(key, [])
        severity = severities.get(key, "critical")
        row = {
            "case_id": case_id,
            "assertion_id": assertion_id,
            "severity": severity,
            "passes": sum(values),
            "failures": len(values) - sum(values),
            "samples": len(values),
            "classification": "pass",
        }
        if len(values) < expected_runs:
            row["classification"] = "missing"
            missing.append(row)
        elif severity.lower() == "critical":
            failures = row["failures"]
            if failures >= fail_threshold:
                row["classification"] = "regression"
                regressions.append(row)
            elif failures > 0:
                row["classification"] = "flaky"
                flaky.append(row)
        elif row["failures"] > 0:
            row["classification"] = "advisory"
            advisory.append(row)
        rows.append(row)

    if infra_errors or missing:
        status = "invalid"
        exit_code = 2
    elif regressions:
        status = "regression"
        exit_code = 1
    elif flaky:
        status = "flaky"
        exit_code = 1
    else:
        status = "pass"
        exit_code = 0

    return {
        "schema_version": 1,
        "expected_runs": expected_runs,
        "fail_threshold": fail_threshold,
        "status": status,
        "exit_code": exit_code,
        "summary": {
            "assertions": len(rows),
            "regressions": len(regressions),
            "flaky": len(flaky),
            "advisory": len(advisory),
            "missing": len(missing),
            "infra_errors": len(infra_errors),
        },
        "coverage": (
            {
                "expected_cases": sorted(expected),
                "observed_cases": sorted(observed_cases),
                "missing_cases": sorted(expected - observed_cases),
            }
            if expected
            else None
        ),
        "assertions": rows,
        "regressions": regressions,
        "flaky": flaky,
        "advisory": advisory,
        "missing": missing,
        "infra_errors": infra_errors,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Live SUT gate",
        "",
        f"- Status: **{result['status']}**",
        f"- Samples: {result['expected_runs']}",
        f"- Failure threshold: {result['fail_threshold']}",
        "",
        "| Case | Assertion | Severity | Passes | Failures | Classification |",
        "|---|---|---|---:|---:|---|",
    ]
    for row in result["assertions"]:
        lines.append(
            f"| {row['case_id']} | {row['assertion_id']} | {row['severity']} | "
            f"{row['passes']} | {row['failures']} | {row['classification']} |"
        )
    coverage = result.get("coverage")
    if coverage:
        missing = coverage.get("missing_cases") or []
        lines.extend(
            [
                "",
                "## Coverage",
                "",
                f"- Expected cases: {len(coverage.get('expected_cases', []))}",
                f"- Observed cases: {len(coverage.get('observed_cases', []))}",
                f"- Missing cases: {', '.join(missing) if missing else 'none'}",
            ]
        )
    if result["infra_errors"]:
        lines.extend(["", "## Infrastructure errors", ""])
        for item in result["infra_errors"]:
            lines.append(f"- {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", nargs="+", type=Path, required=True)
    parser.add_argument("--expected-runs", type=int, default=3)
    parser.add_argument("--fail-threshold", type=int, default=2)
    parser.add_argument(
        "--cases-path",
        type=Path,
        help="Case file or directory used to derive the required coverage set.",
    )
    parser.add_argument(
        "--risk",
        action="append",
        choices=("critical", "high", "medium", "low"),
        help="Risk levels to require; repeatable and only valid with --cases-path.",
    )
    parser.add_argument(
        "--exclude-case",
        action="append",
        dest="exclude_cases",
        help="Case ID or base ID excluded from the required coverage set; repeatable.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.expected_runs < 1:
        parser.error("--expected-runs must be at least 1")
    if args.fail_threshold < 1:
        parser.error("--fail-threshold must be at least 1")
    if args.fail_threshold > args.expected_runs:
        parser.error("--fail-threshold cannot exceed --expected-runs")
    if args.risk and not args.cases_path:
        parser.error("--risk requires --cases-path")

    expected_cases: set[str] | None = None
    if args.cases_path:
        from agent_regression_gate.cases.loader import load_cases

        collection = load_cases(args.cases_path)
        risks = set(args.risk or [])
        excluded = set(args.exclude_cases or [])
        known = {case.id for case in collection.cases}
        known.update(case.base_id for case in collection.cases if case.base_id)
        unknown_excluded = excluded - known
        if unknown_excluded:
            parser.error(
                "Unknown excluded case id(s): "
                + ", ".join(sorted(unknown_excluded))
            )
        expected_cases = {
            case.id
            for case in collection.cases
            if (not risks or case.risk_level in risks)
            and case.id not in excluded
            and (case.base_id or case.id) not in excluded
        }
        if not expected_cases:
            parser.error("--cases-path/--risk selected no cases")

    reports = [_load_report(path) for path in args.reports]
    result = evaluate(
        reports,
        expected_runs=args.expected_runs,
        fail_threshold=args.fail_threshold,
        expected_cases=expected_cases,
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.summary.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8")
    print(f"Live SUT gate: {result['status']}")
    print(
        "regressions: {regressions}; flaky: {flaky}; advisory: {advisory}; "
        "missing: {missing}; infra: {infra_errors}".format(
            **result["summary"]
        )
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
