"""FastAPI application for the local, single-user Agent Regression Gate console.

Run only on loopback. The web frontend talks to this service through a same-origin
Next.js rewrite; this service intentionally has no public-user authentication model.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..cases import load_cases
from ..comparison.diff import compare_reports, render_diff_markdown
from ..config import GateConfig, load_config, safe_url
from ..errors import GateError
from ..execution.runner import run_suite
from ..models import new_id
from ..sut.chatkit_adapter import ChatKitAdapter
from .store import LocalStore, now_iso

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_RISKS = {"critical", "high", "medium", "low"}
_STATUSES = {"queued", "running", "pass", "fail", "error", "incomplete"}


class RunRequest(BaseModel):
    case_ids: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    risks: list[str] = Field(default_factory=list, max_length=4)
    fail_on: Literal["critical", "high", "medium", "low", "any"] = "critical"


class BaselineRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=1000)


class ComparisonRequest(BaseModel):
    baseline_name: str = Field(min_length=1, max_length=80)
    current_run_id: str = Field(min_length=1, max_length=128)


class RuntimeSettingsRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    revision: str = Field(default="", max_length=128)
    request_timeout_seconds: float = Field(gt=0, le=600)
    execution_mode: Literal["deterministic", "live"]


def _load_local_config() -> GateConfig:
    configured = os.environ.get("GATE_CONFIG")
    if configured:
        path = Path(configured)
    else:
        path = Path("config/gate.yaml")
        if not path.is_file():
            path = Path("config/gate.example.yaml")
    return load_config(path, require_model_credentials=False)


def _local_store() -> LocalStore:
    root = Path(os.environ.get("GATE_DATA_DIR", "data"))
    return LocalStore(root / "gate.sqlite3")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = _load_local_config()
    store = _local_store()
    store.initialize()
    interrupted = store.recover_interrupted_runs()
    runtime_settings = store.get_runtime_settings()
    if runtime_settings:
        if runtime_settings.get("base_url"):
            config.sut.base_url = runtime_settings["base_url"]
        if runtime_settings.get("request_timeout_seconds"):
            config.sut.request_timeout_seconds = float(runtime_settings["request_timeout_seconds"])
        if runtime_settings.get("execution_mode"):
            config.model.execution_mode = runtime_settings["execution_mode"]
    app.state.config = config
    app.state.store = store
    app.state.run_lock = asyncio.Lock()
    app.state.tasks = set()
    app.state.started_at = now_iso()
    app.state.recovered_runs = interrupted
    app.state.runtime_settings = runtime_settings
    yield
    tasks = list(app.state.tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="Agent Regression Gate API",
    description="Local single-user API for cases, runs, traces, reports and baselines.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)


def _config() -> GateConfig:
    return app.state.config


def _store() -> LocalStore:
    return app.state.store


def _safe_revision() -> str | None:
    runtime = app.state.runtime_settings if hasattr(app.state, "runtime_settings") else {}
    if "revision" in runtime:
        override = runtime["revision"]
        return str(override)[:128] if override else None
    revision = os.environ.get("GATE_SUT_REVISION")
    if revision:
        return revision[:128]
    lock_file = Path("config/sut.lock.yaml")
    try:
        import yaml
        payload = yaml.safe_load(lock_file.read_text(encoding="utf-8")) or {}
        value = payload.get("sut", {}).get("revision")
        return value if isinstance(value, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def _case_document(case: Any) -> dict[str, Any]:
    return {
        "id": case.id,
        "base_id": case.base_id or case.id,
        "version": case.version,
        "name": case.name,
        "description": case.description,
        "risk_level": case.risk_level,
        "tags": case.tags,
        "turns": case.turns,
        "rules": [
            {"id": rule.id, "type": rule.type, "severity": rule.severity,
             "description": rule.description, "params": rule.params}
            for rule in case.rules
        ],
        "parameters": case.parameters,
        "preconditions": case.preconditions,
        "source": "version-controlled case YAML",
    }


def _load_case_collection():
    try:
        return load_cases(_config().run.cases_path)
    except GateError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Case collection could not be loaded from the configured path.") from exc


def _select_cases(request: RunRequest):
    collection = _load_case_collection()
    if any(risk not in _RISKS for risk in request.risks):
        raise HTTPException(status_code=422, detail="Unknown risk level in run filters.")
    known = {case.id for case in collection.cases}
    known.update(case.base_id for case in collection.cases if case.base_id)
    missing = set(request.case_ids) - known
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown case ID(s): {', '.join(sorted(missing))}.")
    selected = [
        case for case in collection.cases
        if (not request.case_ids or case.id in request.case_ids or case.base_id in request.case_ids)
        and (not request.tags or set(request.tags).intersection(case.tags))
        and (not request.risks or case.risk_level in request.risks)
    ]
    if not selected:
        raise HTTPException(status_code=422, detail="Run filters matched no cases.")
    return collection, selected


def _run_output_paths(record: dict[str, Any]) -> tuple[Path, Path]:
    config = _config()
    root = config.run.reports_dir.resolve()
    json_path = Path(record["report_json_path"]).resolve()
    markdown_path = Path(record["report_md_path"]).resolve()
    try:
        json_path.relative_to(root)
        markdown_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run report was not found in the configured reports directory.") from exc
    return json_path, markdown_path


def _read_report(record: dict[str, Any]) -> dict[str, Any]:
    json_path, _ = _run_output_paths(record)
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="The saved run report is unavailable.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="The saved run report has an invalid format.")
    return data


async def _execute_run(run_id: str, selected: list[Any], fail_on: str) -> None:
    store = _store()
    config = _config()
    store.update_run(run_id, status="running", started_at=now_iso())
    try:
        output_base = (config.run.reports_dir / "runs" / run_id).resolve()
        report, json_path, markdown_path = await run_suite(
            config, selected, fail_on=fail_on, output=output_base, run_id=run_id,
        )
        gate = report.get("gate", {})
        if gate.get("errors", 0):
            status = "error"
        elif gate.get("incomplete", 0):
            status = "incomplete"
        elif gate.get("exit_code", 1) == 0:
            status = "pass"
        else:
            status = "fail"
        store.update_run(
            run_id,
            status=status,
            completed_at=report.get("completed_at") or now_iso(),
            summary_json=report.get("summary", {}),
            gate_json=gate,
            report_json_path=str(json_path.resolve()),
            report_md_path=str(markdown_path.resolve()),
        )
    except asyncio.CancelledError:
        store.update_run(run_id, status="error", completed_at=now_iso(), error_message="The local API stopped before this run completed.")
        raise
    except Exception as exc:
        # Store only a stable error class. Do not leak exception text, which may contain request data.
        store.update_run(
            run_id, status="error", completed_at=now_iso(),
            error_message=f"Run failed before a report was finalized ({type(exc).__name__}).",
        )
    finally:
        app.state.run_lock.release()


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "started_at": app.state.started_at,
        "recovered_interrupted_runs": app.state.recovered_runs,
        "storage": "sqlite",
    }


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    config = _config()
    provider = os.environ.get("LLM_PROVIDER", config.model.provider)
    key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
    return {
        "sut": {
            "base_url": safe_url(config.sut.base_url),
            "health_path": config.sut.health_path,
            "request_timeout_seconds": config.sut.request_timeout_seconds,
            "start_mode": config.sut.start_mode,
            "revision": _safe_revision(),
        },
        "model_metadata": {
            "provider_hint": provider,
            "execution_mode_hint": config.model.execution_mode,
            "credential_configured": bool(os.environ.get(key_name)),
            "credential_variable": key_name,
            "notice": "These are Gate-side hints; the SUT independently chooses its model configuration.",
        },
        "storage": {
            "sqlite_path": str(_store().path),
            "reports_dir": str(config.run.reports_dir.resolve()),
            "cases_path": str(config.run.cases_path),
        },
    }


@app.put("/api/settings")
async def update_settings(request: RuntimeSettingsRequest) -> dict[str, Any]:
    if app.state.run_lock.locked():
        raise HTTPException(status_code=409, detail="SUT settings cannot change while an evaluation is running.")
    parts = urlsplit(request.base_url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPException(status_code=422, detail="SUT URL must be an http(s) URL without credentials, query, or fragment.")
    values = {
        "base_url": request.base_url.strip().rstrip("/"),
        "revision": request.revision.strip(),
        "request_timeout_seconds": request.request_timeout_seconds,
        "execution_mode": request.execution_mode,
    }
    _store().save_runtime_settings(values)
    app.state.runtime_settings = values
    _config().sut.base_url = values["base_url"]
    _config().sut.request_timeout_seconds = values["request_timeout_seconds"]
    _config().model.execution_mode = values["execution_mode"]
    return {"saved": True, "settings": await settings()}


@app.post("/api/sut/check")
async def check_sut() -> dict[str, Any]:
    adapter = ChatKitAdapter(_config().sut)
    try:
        result = await adapter.health_check()
        return {
            "healthy": result.healthy,
            "status_code": result.status_code,
            "latency_ms": round(result.latency_ms, 1),
            "base_url": safe_url(_config().sut.base_url),
        }
    except GateError as exc:
        return JSONResponse(status_code=503, content={"healthy": False, "error": exc.message})
    finally:
        await adapter.aclose()


@app.get("/api/cases")
async def list_cases(
    risk: str | None = None,
    tag: str | None = None,
    q: str | None = Query(default=None, max_length=120),
) -> dict[str, Any]:
    collection = _load_case_collection()
    cases = [_case_document(case) for case in collection.cases]
    if risk:
        if risk not in _RISKS:
            raise HTTPException(status_code=422, detail="Unknown risk level.")
        cases = [case for case in cases if case["risk_level"] == risk]
    if tag:
        cases = [case for case in cases if tag in case["tags"]]
    if q:
        needle = q.casefold()
        cases = [case for case in cases if needle in " ".join([case["id"], case["name"], case["description"], *case["tags"]]).casefold()]
    return {
        "cases": cases,
        "count": len(cases),
        "template_count": len({case["base_id"] for case in cases}),
        "source_files": collection.source_files,
    }


@app.get("/api/dashboard")
async def dashboard() -> dict[str, Any]:
    recent = _store().list_runs(limit=50)
    statuses = {status: 0 for status in _STATUSES}
    for run in recent:
        statuses[run["status"]] = statuses.get(run["status"], 0) + 1
    completed = [run for run in recent if run["status"] in {"pass", "fail", "error", "incomplete"}]
    total_cases = sum((run.get("summary") or {}).get("case_count", 0) for run in completed)
    passed_cases = sum((run.get("summary") or {}).get("passed", 0) for run in completed)
    critical_failures = sum((run.get("gate") or {}).get("critical_failures", 0) for run in completed)
    return {
        "recent_runs": recent[:8],
        "run_count": _store().count_runs(),
        "active_runs": statuses["queued"] + statuses["running"],
        "pass_rate": round(100 * passed_cases / total_cases, 1) if total_cases else None,
        "critical_failures": critical_failures,
        "sut_revision": _safe_revision(),
        "statuses": statuses,
    }


@app.get("/api/runs")
async def list_runs(
    status: str | None = None,
    tag: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if status and status not in _STATUSES:
        raise HTTPException(status_code=422, detail="Unknown run status.")
    runs = _store().list_runs(status=status, tag=tag, include_archived=include_archived, limit=limit, offset=offset)
    return {"runs": runs, "count": len(runs), "limit": limit, "offset": offset}


@app.post("/api/runs", status_code=202)
async def start_run(request: RunRequest) -> dict[str, Any]:
    if app.state.run_lock.locked():
        raise HTTPException(status_code=409, detail="A run is already active. Wait for it to finish before starting another.")
    collection, selected = _select_cases(request)
    acquired = await app.state.run_lock.acquire()
    if not acquired:
        raise HTTPException(status_code=409, detail="A run is already active.")
    run_id = new_id()
    tags = sorted({tag for case in selected for tag in case.tags})
    filters = {"case_ids": request.case_ids, "tags": request.tags, "risks": request.risks, "case_tags": tags}
    try:
        _store().create_run(run_id, fail_on=request.fail_on, case_count=len(selected), filters=filters)
        task = asyncio.create_task(_execute_run(run_id, selected, request.fail_on), name=f"gate-run-{run_id}")
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
    except Exception:
        app.state.run_lock.release()
        raise
    return {"run_id": run_id, "status": "queued", "case_count": len(selected), "fail_on": request.fail_on}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    record = _store().get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found.")
    response: dict[str, Any] = {"run": record}
    if record.get("report_json_path"):
        response["report"] = _read_report(record)
    return response


@app.post("/api/runs/{run_id}/archive")
async def archive_run(run_id: str) -> dict[str, Any]:
    record = _store().get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found.")
    if record["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="An active run cannot be archived.")
    _store().set_run_archived(run_id, True)
    return {"run": _store().get_run(run_id)}


@app.post("/api/runs/{run_id}/unarchive")
async def unarchive_run(run_id: str) -> dict[str, Any]:
    record = _store().get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found.")
    _store().set_run_archived(run_id, False)
    return {"run": _store().get_run(run_id)}


@app.get("/api/runs/{run_id}/traces/{case_id}")
async def get_trace(run_id: str, case_id: str) -> dict[str, Any]:
    record = _store().get_run(run_id)
    if not record or not record.get("report_json_path"):
        raise HTTPException(status_code=404, detail="Run trace is not available yet.")
    report = _read_report(record)
    case = next((item for item in report.get("cases", []) if item.get("case_id") == case_id), None)
    if not case or not case.get("trace_path"):
        raise HTTPException(status_code=404, detail="Trace for this case is not available.")
    trace_root = (_config().run.reports_dir / "traces").resolve()
    trace_path = Path(case["trace_path"])
    if not trace_path.is_absolute():
        trace_path = Path.cwd() / trace_path
    trace_path = trace_path.resolve()
    try:
        trace_path.relative_to(trace_root)
        value = json.loads(trace_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Sanitized trace file could not be read.") from exc
    return value


@app.get("/api/runs/{run_id}/report/{format_name}")
async def download_report(run_id: str, format_name: Literal["json", "md"]):
    record = _store().get_run(run_id)
    if not record or not record.get("report_json_path"):
        raise HTTPException(status_code=404, detail="Report is not available yet.")
    json_path, markdown_path = _run_output_paths(record)
    path = json_path if format_name == "json" else markdown_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report file was not found.")
    return FileResponse(path, filename=f"agent-regression-gate-{run_id}.{format_name}")


@app.get("/api/baselines")
async def list_baselines() -> dict[str, Any]:
    baselines = _store().list_baselines()
    return {"baselines": baselines, "count": len(baselines)}


@app.post("/api/baselines", status_code=201)
async def promote_baseline(request: BaselineRequest) -> dict[str, Any]:
    name = request.name.strip()
    reason = request.reason.strip()
    if not _SAFE_NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="Baseline name must use 1–80 safe filename characters.")
    if not reason:
        raise HTTPException(status_code=422, detail="A review reason is required to promote a baseline.")
    if _store().get_baseline(name):
        raise HTTPException(status_code=409, detail="This baseline name already exists; choose another name to preserve review history.")
    record = _store().get_run(request.run_id)
    if not record or not record.get("report_json_path"):
        raise HTTPException(status_code=404, detail="Completed run report not found.")
    report = _read_report(record)
    if not report.get("comparison_context"):
        raise HTTPException(status_code=409, detail="This report lacks P6 compatibility metadata and cannot be promoted.")
    target = (_config().run.baselines_dir / f"{name}.json").resolve()
    baseline_root = _config().run.baselines_dir.resolve()
    try:
        target.relative_to(baseline_root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid baseline path.") from exc
    envelope = {
        "baseline_schema_version": 1,
        "name": name,
        "reason": reason,
        "saved_at": now_iso(),
        "report": report,
    }
    _atomic_json(target, envelope)
    _store().save_baseline(name=name, run_id=request.run_id, reason=reason, file_path=str(target))
    return {"name": name, "run_id": request.run_id, "reason": reason, "saved_at": envelope["saved_at"]}


@app.post("/api/comparisons", status_code=201)
async def create_comparison(request: ComparisonRequest) -> dict[str, Any]:
    baseline = _store().get_baseline(request.baseline_name)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found.")
    current_record = _store().get_run(request.current_run_id)
    if not current_record or not current_record.get("report_json_path"):
        raise HTTPException(status_code=404, detail="Current run report not found.")
    try:
        baseline_doc = json.loads(Path(baseline["file_path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Baseline report file could not be read.") from exc
    current_report = _read_report(current_record)
    result = compare_reports(baseline_doc.get("report", baseline_doc), current_report)
    comparison_id = uuid4().hex
    output_root = (_config().run.reports_dir / "comparisons").resolve()
    json_path, markdown_path = output_root / f"{comparison_id}.json", output_root / f"{comparison_id}.md"
    _atomic_json(json_path, result)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_diff_markdown(result), encoding="utf-8")
    _store().save_comparison(
        comparison_id=comparison_id, baseline_name=request.baseline_name,
        current_run_id=request.current_run_id, status=result["status"],
        json_path=str(json_path), markdown_path=str(markdown_path),
    )
    return {"comparison_id": comparison_id, "result": result}


@app.get("/api/comparisons/{comparison_id}")
async def get_comparison(comparison_id: str) -> dict[str, Any]:
    value = _store().get_comparison(comparison_id)
    if not value:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    try:
        result = json.loads(Path(value["json_path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Comparison report file could not be read.") from exc
    return {"comparison": value, "result": result}


@app.get("/api/comparisons/{comparison_id}/report/json")
async def download_comparison_json(comparison_id: str):
    value = _store().get_comparison(comparison_id)
    if not value:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    path = Path(value["json_path"]).resolve()
    try:
        path.relative_to((_config().run.reports_dir / "comparisons").resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Comparison report is outside the configured reports directory.") from exc
    return FileResponse(path, filename=f"agent-regression-diff-{comparison_id}.json")


@app.get("/api/comparisons/{comparison_id}/report.md")
async def download_comparison(comparison_id: str):
    value = _store().get_comparison(comparison_id)
    if not value:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    path = Path(value["markdown_path"]).resolve()
    try:
        path.relative_to((_config().run.reports_dir / "comparisons").resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Comparison report is outside the configured reports directory.") from exc
    return FileResponse(path, filename=f"agent-regression-diff-{comparison_id}.md")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
