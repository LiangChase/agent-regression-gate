"""Command line entry point. Execution commands are added in later phases."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from .config import load_config, safe_url
from .errors import GateError
from .logging_config import configure_logging
from .sut.chatkit_adapter import ChatKitAdapter
from .sut.lifecycle import SutLifecycle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate",
        description="Validate agent behavior rules and block critical regressions.",
        epilog="doctor is implemented; run and validate-cases arrive in later phases.",
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
    for name, help_text in (
        ("run", "Execute cases (available in a later phase)."),
        ("doctor", "Check the SUT connection (available in P2)."),
        ("validate-cases", "Validate case files (available in P4)."),
    ):
        subparsers.add_parser(name, help=help_text)
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
            "execution_mode": args.model_execution_mode,
            "provider": args.model_provider,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in {"config-check", "doctor"}:
        print(f"'{args.command}' is not available yet; see the phase plan.", file=sys.stderr)
        return 12

    try:
        config = load_config(
            args.config,
            cli_overrides=_overrides(args),
            require_model_credentials=args.command != "doctor",
        )
        logger = configure_logging(config.logging.level, config.logging.format)
        if args.command == "doctor":
            return asyncio.run(_doctor(config, logger))
    except GateError as exc:
        print(f"ERROR[{exc.category.value}]: {exc.message}", file=sys.stderr)
        return exc.exit_code

    if args.json:
        print(json.dumps(config.safe_dict(), ensure_ascii=False, indent=2))
    else:
        logger.info("Configuration is valid.", extra={"event": "config_validated"})
        print(f"Configuration valid: {config.config_path}")
    return 0


async def _doctor(config, logger) -> int:
    adapter = ChatKitAdapter(config.sut)
    lifecycle = SutLifecycle(config.sut, adapter)
    try:
        status = await lifecycle.start()
        logger.info(
            "SUT health check passed.",
            extra={"event": "sut_healthy", "sut_url": config.sut.base_url, "duration_ms": status.latency_ms},
        )
        print(
            f"SUT healthy: {safe_url(config.sut.base_url)} "
            f"(HTTP {status.status_code}, {status.latency_ms:.1f} ms)"
        )
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
