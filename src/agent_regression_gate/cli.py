"""CLI for configuration, SUT diagnostics, case validation, and regression runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from .cases import load_cases
from .config import load_config, safe_url
from .errors import ConfigurationError, GateError
from .execution.runner import run_suite
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
