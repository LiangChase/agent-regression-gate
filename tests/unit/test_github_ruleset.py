from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULESET = REPO_ROOT / ".github" / "rulesets" / "main-branch-protection.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "regression.yml"
SCRIPT = REPO_ROOT / "scripts" / "apply_github_ruleset.py"


def load_script():
    spec = importlib.util.spec_from_file_location("apply_github_ruleset", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def ruleset_payload() -> dict:
    return json.loads(RULESET.read_text(encoding="utf-8"))


def workflow_job_name() -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return document["jobs"]["deterministic-gate"]["name"]


def test_ruleset_required_check_matches_workflow_job_name():
    payload = ruleset_payload()
    job_name = workflow_job_name()
    checks = next(
        rule for rule in payload["rules"] if rule["type"] == "required_status_checks"
    )
    contexts = [
        item["context"]
        for item in checks["parameters"]["required_status_checks"]
    ]
    assert contexts == [job_name]


def test_ruleset_targets_main_and_has_required_guardrails():
    payload = ruleset_payload()
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert "refs/heads/main" in payload["conditions"]["ref_name"]["include"]
    assert payload["bypass_actors"] == []

    types = {rule["type"] for rule in payload["rules"]}
    assert {"pull_request", "required_status_checks", "deletion", "non_fast_forward"} <= types

    pull_request = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    assert pull_request["parameters"]["required_approving_review_count"] == 0

    checks = next(rule for rule in payload["rules"] if rule["type"] == "required_status_checks")
    assert checks["parameters"]["strict_required_status_checks_policy"] is True


def test_validator_accepts_the_checked_in_ruleset():
    module = load_script()
    assert module.validate_ruleset(ruleset_payload(), workflow_job_name()) == []


def test_validator_rejects_a_stale_required_check_name():
    module = load_script()
    payload = copy.deepcopy(ruleset_payload())
    checks = next(rule for rule in payload["rules"] if rule["type"] == "required_status_checks")
    checks["parameters"]["required_status_checks"][0]["context"] = "old job name"
    errors = module.validate_ruleset(payload, workflow_job_name())
    assert any("required status check" in error for error in errors)


def test_dry_run_cli_does_not_require_a_token():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert workflow_job_name() in result.stdout
    assert '"target": "branch"' in result.stdout
