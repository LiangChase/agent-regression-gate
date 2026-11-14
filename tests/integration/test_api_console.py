from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_report(run_id: str, *, assertion_passed: bool = True):
    return {
        "run_id": run_id,
        "started_at": now_iso(),
        "completed_at": now_iso(),
        "fail_on": "critical",
        "sut_revision": "rev-test",
        "model": {
            "provider": "deepseek",
            "execution_mode": "deterministic",
            "model_name": "deepseek-flash",
        },
        "comparison_context": {
            "case_set_fingerprint": "fingerprint-1",
            "trace_schema_version": 1,
            "evaluator_version": "deterministic-v3",
            "gate_version": "0.1.0",
            "sut_revision": "rev-test",
            "model": {
                "provider": "deepseek",
                "model_name": "deepseek-flash",
                "execution_mode": "deterministic",
            },
        },
        "summary": {
            "case_count": 1,
            "passed": 1 if assertion_passed else 0,
            "failed": 0 if assertion_passed else 1,
            "errors": 0,
            "incomplete": 0,
            "assertion_count": 1,
        },
        "gate": {
            "status": "pass" if assertion_passed else "fail",
            "critical_failures": 0 if assertion_passed else 1,
            "blocking_assertions": 0 if assertion_passed else 1,
            "errors": 0,
            "incomplete": 0,
            "exit_code": 0 if assertion_passed else 1,
        },
        "cases": [
            {
                "case_id": "AIR-01",
                "run_id": run_id,
                "status": "pass" if assertion_passed else "fail",
                "assertions": [
                    {
                        "assertion_id": "AIR-01-R1",
                        "name": "tool_must_be_called",
                        "passed": assertion_passed,
                        "severity": "critical",
                        "expected": {"tool": "flight_status_tool"},
                        "actual": {"count": 1 if assertion_passed else 0},
                        "evidence_event_ids": ["event-1"],
                        "message": "ok" if assertion_passed else "failed",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def api(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    baselines = tmp_path / "baselines"
    data = tmp_path / "data"
    for path in (reports, baselines, data):
        path.mkdir()

    config = yaml.safe_load((REPO_ROOT / "config/gate.example.yaml").read_text(encoding="utf-8"))
    config["run"]["reports_dir"] = str(reports)
    config["run"]["baselines_dir"] = str(baselines)
    config["run"]["cases_path"] = str(REPO_ROOT / "cases/airline")
    config_path = tmp_path / "gate.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")

    monkeypatch.setenv("GATE_CONFIG", str(config_path))
    monkeypatch.setenv("GATE_DATA_DIR", str(data))

    from agent_regression_gate.api.app import app

    with TestClient(app) as client:
        yield client, app, reports, baselines


def seed_run(app, reports: Path, run_id: str, *, status: str = "pass", assertion_passed: bool = True):
    report = make_report(run_id, assertion_passed=assertion_passed)
    runs_dir = reports / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / f"{run_id}.json"
    md_path = runs_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    md_path.write_text("# run report\n", encoding="utf-8")

    store = app.state.store
    store.create_run(run_id, fail_on="critical", case_count=1, filters={})
    store.update_run(
        run_id,
        status=status,
        started_at=now_iso(),
        completed_at=now_iso(),
        summary_json=report["summary"],
        gate_json=report["gate"],
        report_json_path=str(json_path),
        report_md_path=str(md_path),
    )
    return report


def test_health_cases_and_dashboard(api):
    client, _, _, _ = api
    assert client.get("/api/health").status_code == 200
    cases = client.get("/api/cases").json()
    assert len(cases["cases"]) == 16
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["run_count"] == 0
    assert dashboard["active_runs"] == 0


def test_archive_and_unarchive_run_visibility(api):
    client, app, reports, _ = api
    seed_run(app, reports, "run-1")

    assert client.post("/api/runs/run-1/archive").status_code == 200
    default_runs = client.get("/api/runs").json()["runs"]
    assert default_runs == []

    archived_runs = client.get("/api/runs?include_archived=true").json()["runs"]
    assert [run["run_id"] for run in archived_runs] == ["run-1"]
    assert archived_runs[0]["archived_at"] is not None

    assert client.get("/api/dashboard").json()["run_count"] == 0
    assert client.post("/api/runs/run-1/unarchive").status_code == 200
    assert [run["run_id"] for run in client.get("/api/runs").json()["runs"]] == ["run-1"]


def test_active_run_cannot_be_archived(api):
    client, app, reports, _ = api
    seed_run(app, reports, "run-active", status="running")
    app.state.store.update_run("run-active", status="running")
    response = client.post("/api/runs/run-active/archive")
    assert response.status_code == 409


def test_run_report_downloads(api):
    client, app, reports, _ = api
    seed_run(app, reports, "run-1")
    json_response = client.get("/api/runs/run-1/report/json")
    md_response = client.get("/api/runs/run-1/report/md")
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert md_response.status_code == 200
    assert md_response.headers["content-type"].startswith("text/markdown")


def test_baseline_create_duplicate_and_delete(api):
    client, app, reports, baselines = api
    seed_run(app, reports, "run-1")

    created = client.post(
        "/api/baselines",
        json={"run_id": "run-1", "name": "release-test", "reason": "reviewed"},
    )
    assert created.status_code == 201
    baseline_file = baselines / "release-test.json"
    assert baseline_file.is_file()

    duplicate = client.post(
        "/api/baselines",
        json={"run_id": "run-1", "name": "release-test", "reason": "again"},
    )
    assert duplicate.status_code == 409

    deleted = client.delete("/api/baselines/release-test")
    assert deleted.status_code == 200
    assert deleted.json() == {"name": "release-test", "deleted": True, "comparison_references": 0}
    assert not baseline_file.exists()
    assert client.delete("/api/baselines/release-test").status_code == 404


def test_comparison_create_and_downloads(api):
    client, app, reports, _ = api
    seed_run(app, reports, "baseline-run", assertion_passed=True)
    seed_run(app, reports, "current-run", assertion_passed=False)

    assert client.post(
        "/api/baselines",
        json={"run_id": "baseline-run", "name": "reviewed", "reason": "baseline"},
    ).status_code == 201

    created = client.post(
        "/api/comparisons",
        json={"baseline_name": "reviewed", "current_run_id": "current-run"},
    )
    assert created.status_code == 201
    comparison = created.json()
    assert comparison["result"]["status"] == "comparable"
    assert len(comparison["result"]["new_failures"]) == 1

    comparison_id = comparison["comparison_id"]
    assert client.get(f"/api/comparisons/{comparison_id}").status_code == 200

    markdown = client.get(f"/api/comparisons/{comparison_id}/report.md")
    assert markdown.status_code == 200
    assert "# 基线对比报告" in markdown.text
    assert "AIR-01-R1" in markdown.text

    json_report = client.get(f"/api/comparisons/{comparison_id}/report/json")
    assert json_report.status_code == 200
    assert json_report.headers["content-type"].startswith("application/json")
    assert "attachment" in json_report.headers["content-disposition"]


def test_deleting_baseline_keeps_historical_comparisons(api):
    client, app, reports, _ = api
    seed_run(app, reports, "baseline-run")
    seed_run(app, reports, "current-run")
    client.post("/api/baselines", json={"run_id": "baseline-run", "name": "reviewed", "reason": "baseline"})
    comparison = client.post(
        "/api/comparisons",
        json={"baseline_name": "reviewed", "current_run_id": "current-run"},
    ).json()

    deleted = client.delete("/api/baselines/reviewed").json()
    assert deleted["comparison_references"] == 1
    assert client.get(f"/api/comparisons/{comparison['comparison_id']}").status_code == 200
