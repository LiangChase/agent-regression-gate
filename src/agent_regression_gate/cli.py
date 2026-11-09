"""CLI for configuration, SUT diagnostics, case validation, and regression runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence

from .cases import load_cases
from .comparison.diff import compare_reports, render_diff_markdown
from .config import load_config, safe_url
from .errors import ConfigurationError, GateError
from .execution.runner import run_suite
from .evaluators.semantic import make_judge, score_report_evidence
from .logging_config import configure_logging
from .sut.chatkit_adapter import ChatKitAdapter
from .sut.lifecycle import SutLifecycle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate",
        description="Validate agent behavior rules and block critical regressions.",
        epilog="Deterministic evaluators check recorded behavior; they do not make external model calls deterministic.",
    )
    parser.add_argument("--config", help="Configuration YAML path (default: GATE_CONFIG or config/gate.yaml).")
    parser.add_argument("--sut-base-url", help="Override sut.base_url for this invocation.")
    parser.add_argument("--model-execution-mode", choices=("deterministic", "live"))
    parser.add_argument("--model-provider", choices=("openai", "deepseek"))
    parser.add_argument("--request-timeout-seconds", type=float)
    parser.add_argument("--startup-timeout-seconds", type=float)
    parser.add_argument("--shutdown-timeout-seconds", type=float)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("config-check", help="Load and validate effective configuration safely.")
    check.add_argument("--json", action="store_true", help="Print effective settings as JSON.")

    doctor = subparsers.add_parser("doctor", help="Check the SUT connection and lifecycle configuration.")
    doctor.add_argument("--config", dest="sub_config", help=argparse.SUPPRESS)

    validate = subparsers.add_parser("validate-cases", help="Validate case files before execution.")
    validate.add_argument("--config", dest="sub_config", help=argparse.SUPPRESS)
    validate.add_argument("--path", help="Case file or directory (default: run.cases_path).")
    validate.add_argument("--json", action="store_true", help="Print validation summary as JSON.")

    run = subparsers.add_parser("run", help="Execute selected cases and write JSON/Markdown reports.")
    run.add_argument("--config", dest="sub_config", help=argparse.SUPPRESS)
    run.add_argument("--cases-path", help="Override run.cases_path.")
    run.add_argument("--case", action="append", dest="case_ids", help="Case ID to include; repeatable.")
    run.add_argument("--tag", action="append", dest="tags", help="Case tag to include; repeatable.")
    run.add_argument("--risk", action="append", choices=("critical", "high", "medium", "low"), help="Risk level to include; repeatable.")
    run.add_argument("--mode", dest="run_mode", choices=("deterministic", "live"), help="Record intended SUT model mode.")
    run.add_argument("--fail-on", choices=("critical", "high", "medium", "low", "any"), default="critical")
    run.add_argument("--output", help="Report output base path; .json and .md are written.")

    compare = subparsers.add_parser("compare", help="Compare a current run to an explicit baseline.")
    compare.add_argument("--baseline", required=True, help="Baseline JSON file or saved baseline name.")
    compare.add_argument("--current", required=True, help="Current run JSON report.")
    compare.add_argument("--output", help="Output basename (default: reports/comparisons/<run-id>).")

    baseline = subparsers.add_parser("baseline", help="Manage reviewed baseline snapshots.")
    baseline_sub = baseline.add_subparsers(dest="baseline_command", required=True)
    save = baseline_sub.add_parser("save", help="Save a report as a named baseline; never called implicitly.")
    save.add_argument("--report", required=True, help="Sanitized run report JSON.")
    save.add_argument("--name", required=True, help="Baseline name (letters, digits, dot, dash, underscore).")
    save.add_argument("--reason", required=True, help="Review note explaining why this run is trusted.")

    score = subparsers.add_parser("score", help="Run optional semantic scoring on saved trace evidence.")
    score.add_argument("--report", required=True, help="Run report JSON with accessible trace paths.")
    score.add_argument("--provider", choices=("stub", "openai", "deepseek"), default="stub")
    score.add_argument("--model", help="Judge model; defaults to the provider's recommended model.")
    score.add_argument("--output", help="Output JSON path (default: <report>.semantic.json).")
    return parser


def _overrides(args: argparse.Namespace) -> dict[str, dict[str, object]]:
    return {
        "sut": {
            "base_url": args.sut_base_url,
            "request_timeout_seconds": args.request_timeout_seconds,
            "startup_timeout_seconds": args.startup_timeout_seconds,
            "shutdown_timeout_seconds": args.shutdown_timeout_seconds,
        },
        "model": {
            "execution_mode": getattr(args, "run_mode", None) or args.model_execution_mode,
            "provider": args.model_provider,
        },
        "run": {"cases_path": getattr(args, "cases_path", None)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = getattr(args, "sub_config", None) or args.config
    try:
        config = load_config(
            config_path,
            cli_overrides=_overrides(args),
            require_model_credentials=args.command == "config-check",
        )
        logger = configure_logging(config.logging.level, config.logging.format)
        if args.command == "config-check":
            if args.json:
                print(json.dumps(config.safe_dict(), ensure_ascii=False, indent=2))
            else:
                logger.info("Configuration is valid.", extra={"event": "config_validated"})
                print(f"Configuration valid: {config.config_path}")
            return 0
        if args.command == "doctor":
            return asyncio.run(_doctor(config, logger))
        if args.command == "validate-cases":
            collection = load_cases(args.path or config.run.cases_path)
            summary = {
                "valid": True,
                "case_count": len(collection.cases),
                "template_count": len({case.base_id or case.id for case in collection.cases}),
                "case_ids": [case.id for case in collection.cases],
                "rule_count": sum(len(case.rules) for case in collection.cases),
                "source_files": collection.source_files,
            }
            if args.json:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                print(f"Cases valid: {summary['case_count']} cases, {summary['rule_count']} rules")
            return 0
        if args.command == "run":
            collection = load_cases(config.run.cases_path)
            selected = _select_cases(collection.cases, args.case_ids, args.tags, args.risk)
            report, json_path, markdown_path = asyncio.run(
                run_suite(config, selected, fail_on=args.fail_on, output=args.output)
            )
            gate = report["gate"]
            print(f"Gate {gate['status'].upper()}: {report['summary']['passed']}/{report['summary']['case_count']} cases passed")
            print(f"JSON report: {json_path}")
            print(f"Markdown report: {markdown_path}")
            return int(gate["exit_code"])
        if args.command == "compare":
            baseline_doc = _read_json(_baseline_path(args.baseline, config.run.baselines_dir))
            baseline_report = baseline_doc.get("report", baseline_doc)
            current_report = _read_json(args.current)
            result = compare_reports(baseline_report, current_report)
            output = Path(args.output) if args.output else config.run.reports_dir / "comparisons" / str(current_report.get("run_id", "comparison"))
            output.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(output.with_suffix(".json"), result)
            output.with_suffix(".md").write_text(render_diff_markdown(result), encoding="utf-8")
            print(f"Comparison: {result['status']}")
            print(f"New failures: {result['summary']['new_failures']}; fixed: {result['summary']['fixed']}; persistent: {result['summary']['persistent_failures']}")
            print(f"JSON diff: {output.with_suffix('.json')}")
            print(f"Markdown diff: {output.with_suffix('.md')}")
            return 0
        if args.command == "baseline" and args.baseline_command == "save":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.name):
                raise ConfigurationError("Baseline name must contain 1–80 safe filename characters.")
            if not args.reason.strip():
                raise ConfigurationError("Baseline save requires a non-empty review reason.")
            report = _read_json(args.report)
            if not report.get("run_id") or not report.get("comparison_context"):
                raise ConfigurationError("Baseline report is missing run_id or comparison_context metadata.")
            target = config.run.baselines_dir / f"{args.name}.json"
            _atomic_json(target, {
                "baseline_schema_version": 1,
                "name": args.name,
                "reason": args.reason.strip(),
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "report": report,
            })
            print(f"Saved reviewed baseline: {target}")
            return 0
        if args.command == "score":
            report = _read_json(args.report)
            judge = make_judge(args.provider, args.model)
            evidence = score_report_evidence(report)
            scores = asyncio.run(_score_all(judge, evidence))
            target = Path(args.output) if args.output else Path(args.report).with_suffix(".semantic.json")
            _atomic_json(target, {
                "semantic_schema_version": 1,
                "run_id": report.get("run_id"),
                "provider": args.provider,
                "rubric_version": "airline-response-v1",
                "scores": scores,
                "summary": _score_summary(scores),
                "gate_effect": "advisory_only",
            })
            print(f"Semantic scoring: {target}")
            return 10 if any(item.get("status") == "error" for item in scores) else 0
    except GateError as exc:
        print(f"ERROR[{exc.category.value}]: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        error = ConfigurationError(f"Could not prepare the requested operation ({type(exc).__name__}).")
        print(f"ERROR[{error.category.value}]: {error.message}", file=sys.stderr)
        return error.exit_code
    return 12


def _select_cases(cases, case_ids, tags, risks):
    known_ids = {case.id for case in cases}
    known_ids.update(case.base_id for case in cases if case.base_id)
    requested_ids = set(case_ids or [])
    missing_ids = requested_ids - known_ids
    if missing_ids:
        raise ConfigurationError(f"Unknown case id(s): {', '.join(sorted(missing_ids))}.")
    selected = [
        case for case in cases
        if (not requested_ids or case.id in requested_ids or case.base_id in requested_ids)
        and (not tags or set(tags).intersection(case.tags))
        and (not risks or case.risk_level in risks)
    ]
    if not selected:
        raise ConfigurationError("Case filters matched no cases.")
    return selected


def _read_json(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"Could not read JSON document '{path}'.") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON document '{path}' must contain an object.")
    return value


def _baseline_path(value: str, baseline_dir: Path) -> Path:
    path = Path(value)
    if path.is_file():
        return path
    if not path.suffix:
        path = baseline_dir / f"{value}.json"
    if not path.is_file():
        raise ConfigurationError(f"Baseline '{value}' was not found at '{path}'.")
    return path


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


async def _score_all(judge, evidence: list[dict]) -> list[dict]:
    results = []
    for item in evidence:
        if item.get("error") or not item.get("evidence"):
            results.append({"case_id": item["case_id"], "status": "error", "error_category": "trace_evidence_unavailable", "reason": item.get("error", "No trace evidence is available for this case.")})
            continue
        try:
            score = await judge.score(prompt=item["prompt"], evidence={"events": item["evidence"]})
        except Exception as exc:
            score = {"status": "error", "error_category": type(exc).__name__, "reason": "Semantic judge failed; it is not treated as a pass."}
        results.append({"case_id": item["case_id"], **score})
    return results


def _score_summary(scores: list[dict]) -> dict:
    scored = [item["overall_score"] for item in scores if item.get("status") == "scored"]
    return {
        "case_count": len(scores),
        "scored": len(scored),
        "errors": sum(item.get("status") == "error" for item in scores),
        "not_scored": sum(item.get("status") == "not_scored" for item in scores),
        "mean_score": round(sum(scored) / len(scored), 2) if scored else None,
    }


async def _doctor(config, logger) -> int:
    adapter = ChatKitAdapter(config.sut)
    lifecycle = SutLifecycle(config.sut, adapter)
    try:
        status = await lifecycle.start()
        logger.info(
            "SUT health check passed.",
            extra={"event": "sut_healthy", "sut_url": config.sut.base_url, "duration_ms": status.latency_ms},
        )
        print(f"SUT healthy: {safe_url(config.sut.base_url)} (HTTP {status.status_code}, {status.latency_ms:.1f} ms)")
        return 0
    except GateError as exc:
        print(f"ERROR[{exc.category.value}]: {exc.message}", file=sys.stderr)
        if exc.detail:
            logger.error("SUT diagnostic detail: %s", exc.detail)
        return exc.exit_code
    finally:
        await lifecycle.stop()
        await adapter.aclose()


if __name__ == "__main__":
    raise SystemExit(main())
