"""Command line entry point. Execution commands are added in later phases."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .config import load_config
from .errors import GateError
from .logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate",
        description="Validate agent behavior rules and block critical regressions.",
        epilog="P1 provides config-check; run, doctor, and validate-cases arrive in later phases.",
    )
    parser.add_argument("--config", help="Configuration YAML path (default: GATE_CONFIG or config/gate.yaml).")
    parser.add_argument("--sut-base-url", help="Override sut.base_url for this invocation.")
    parser.add_argument("--model-execution-mode", choices=("deterministic", "live"))
    parser.add_argument("--model-provider", choices=("openai", "deepseek"))
    parser.add_argument("--request-timeout-seconds", type=float)
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
        },
        "model": {
            "execution_mode": args.model_execution_mode,
            "provider": args.model_provider,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "config-check":
        print(f"'{args.command}' is not implemented in P1; see the phase plan.", file=sys.stderr)
        return 12

    try:
        config = load_config(args.config, cli_overrides=_overrides(args))
        logger = configure_logging(config.logging.level, config.logging.format)
    except GateError as exc:
        print(f"ERROR[{exc.category.value}]: {exc.message}", file=sys.stderr)
        return exc.exit_code

    if args.json:
        print(json.dumps(config.safe_dict(), ensure_ascii=False, indent=2))
    else:
        logger.info("Configuration is valid.", extra={"event": "config_validated"})
        print(f"Configuration valid: {config.config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
