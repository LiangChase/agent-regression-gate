"""Validate, inspect, or apply the main-branch ruleset for the Gate repository.

The ruleset requires the deterministic PR gate and the live SUT gate. Applying
it requires a GitHub token with Administration read/write access; `dry-run` and
`check` do not modify anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESET = REPO_ROOT / ".github" / "rulesets" / "main-branch-protection.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "regression.yml"
GATE_JOB_ID = "deterministic-gate"
LIVE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-sut-gate.yml"
LIVE_JOB_ID = "live-sut-gate"


def extract_job_name(
    workflow_path: Path = WORKFLOW, job_id: str = GATE_JOB_ID
) -> str:
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    name = document.get("jobs", {}).get(job_id, {}).get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Workflow job '{job_id}' has no stable name.")
    return name


def extract_required_job_names() -> list[str]:
    return [
        extract_job_name(WORKFLOW, GATE_JOB_ID),
        extract_job_name(LIVE_WORKFLOW, LIVE_JOB_ID),
    ]


def normalize_job_names(job_names: str | Iterable[str]) -> list[str]:
    return [job_names] if isinstance(job_names, str) else list(job_names)


def load_ruleset(path: Path = DEFAULT_RULESET) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Ruleset payload must be a JSON object.")
    return payload


def validate_ruleset(
    payload: dict[str, Any], job_names: str | Iterable[str]
) -> list[str]:
    errors: list[str] = []
    if not payload.get("name"):
        errors.append("ruleset name is required")
    if payload.get("target") != "branch":
        errors.append("ruleset target must be 'branch'")
    if payload.get("enforcement") != "active":
        errors.append("ruleset enforcement must be 'active'")

    include = (
        payload.get("conditions", {})
        .get("ref_name", {})
        .get("include", [])
    )
    if "refs/heads/main" not in include:
        errors.append("ruleset must include refs/heads/main")

    types = {
        item.get("type")
        for item in payload.get("rules", [])
        if isinstance(item, dict)
    }
    for required in ("pull_request", "required_status_checks", "deletion", "non_fast_forward"):
        if required not in types:
            errors.append(f"ruleset is missing rule '{required}'")

    checks_rule = next(
        (item for item in payload.get("rules", []) if item.get("type") == "required_status_checks"),
        None,
    )
    parameters = (checks_rule or {}).get("parameters", {})
    contexts = [
        item.get("context")
        for item in parameters.get("required_status_checks", [])
        if isinstance(item, dict)
    ]
    for job_name in normalize_job_names(job_names):
        if job_name not in contexts:
            errors.append(
                f"required status check must include the workflow job name '{job_name}'"
            )
    if parameters.get("strict_required_status_checks_policy") is not True:
        errors.append("strict_required_status_checks_policy must be true")

    if payload.get("bypass_actors"):
        errors.append("bypass_actors must be empty so main cannot bypass the ruleset")
    return errors


def detect_repository() -> str:
    try:
        remote = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Could not detect repository from git remote; pass --repo owner/name.") from exc
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not match:
        raise ValueError("origin is not a GitHub repository; pass --repo owner/name.")
    return f"{match.group(1)}/{match.group(2)}"


def api_request(
    method: str,
    path: str,
    *,
    token: str | None,
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "agent-regression-gate-ruleset",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{API_ROOT}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed with {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the GitHub API: {exc.reason}") from exc


def find_ruleset(repo: str, token: str | None, name: str) -> dict[str, Any] | None:
    rulesets = api_request("GET", f"/repos/{repo}/rulesets?per_page=100", token=token) or []
    for item in rulesets:
        if isinstance(item, dict) and item.get("name") == name:
            ruleset_id = item.get("id")
            if ruleset_id is not None:
                return api_request("GET", f"/repos/{repo}/rulesets/{ruleset_id}", token=token)
            return item
    return None


def command_dry_run(args: argparse.Namespace) -> int:
    payload = load_ruleset(args.ruleset_file)
    job_names = extract_required_job_names()
    errors = validate_ruleset(payload, job_names)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if errors:
        print("\nValidation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"\nValidation OK. Required checks: {', '.join(job_names)}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    payload = load_ruleset(args.ruleset_file)
    job_names = extract_required_job_names()
    errors = validate_ruleset(payload, job_names)
    if errors:
        print("Local ruleset file is invalid:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    repo = args.repo or detect_repository()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        ruleset = find_ruleset(repo, token, payload["name"])
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print("For private repositories, set GH_TOKEN with read access.", file=sys.stderr)
        return 2
    if ruleset is None:
        print(f"FAIL: ruleset '{payload['name']}' is not active on {repo}.")
        return 3

    remote_errors = validate_ruleset(ruleset, job_names)
    if remote_errors:
        print("FAIL: active ruleset does not match the local configuration:")
        for error in remote_errors:
            print(f"- {error}")
        return 1
    print(f"PASS: main is protected by ruleset '{payload['name']}'.")
    print(f"Required checks: {', '.join(job_names)}")
    return 0


def command_apply(args: argparse.Namespace) -> int:
    payload = load_ruleset(args.ruleset_file)
    job_names = extract_required_job_names()
    errors = validate_ruleset(payload, job_names)
    if errors:
        print("Refusing to apply an invalid ruleset:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "GH_TOKEN (or GITHUB_TOKEN) is required with Administration read/write access.",
            file=sys.stderr,
        )
        return 2

    repo = args.repo or detect_repository()
    existing = find_ruleset(repo, token, payload["name"])
    if existing:
        ruleset_id = existing["id"]
        api_request("PUT", f"/repos/{repo}/rulesets/{ruleset_id}", token=token, payload=payload)
        print(f"Updated ruleset '{payload['name']}' (id={ruleset_id}) on {repo}.")
    else:
        result = api_request("POST", f"/repos/{repo}/rulesets", token=token, payload=payload)
        print(f"Created ruleset '{payload['name']}' (id={result.get('id')}) on {repo}.")
    print(f"Required checks: {', '.join(job_names)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="GitHub repository in owner/name form; defaults to origin.")
    parser.add_argument(
        "--ruleset-file",
        type=Path,
        default=DEFAULT_RULESET,
        help="Ruleset JSON file (default: .github/rulesets/main-branch-protection.json).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run", help="Validate and print the payload without network access.")
    dry_run.set_defaults(func=command_dry_run)

    check = subparsers.add_parser("check", help="Read the active ruleset and verify it matches the file.")
    check.set_defaults(func=command_check)

    apply = subparsers.add_parser("apply", help="Create or update the ruleset (requires GH_TOKEN).")
    apply.set_defaults(func=command_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
