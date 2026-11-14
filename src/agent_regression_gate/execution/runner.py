"""Serial case runner that connects SUT adapter, trace store, and evaluators."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..cases.models import Case
from .. import __version__
from ..config import GateConfig
from ..errors import GateError, TraceIncompleteError
from ..evaluators import evaluate_case
from ..models import CaseResult, ResultStatus, new_id, utc_now
from ..reporting import ReportWriter
from ..sut.base import SutAdapter
from ..sut.chatkit_adapter import ChatKitAdapter
from ..sut.lifecycle import SutLifecycle
from ..tracing import TraceBundle, TraceStore, TurnCapture, normalize_trace

_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "warning": 4, "info": 5}
_FAIL_THRESHOLDS = {"critical": 0, "high": 1, "medium": 2, "low": 3, "any": 5}


async def run_suite(
    config: GateConfig,
    cases: Iterable[Case],
    *,
    fail_on: str = "critical",
    output: str | Path | None = None,
    run_id: str | None = None,
    adapter: SutAdapter | None = None,
    lifecycle: Any | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    selected = list(cases)
    if not selected:
        raise ValueError("At least one case must be selected.")
    if fail_on not in _FAIL_THRESHOLDS:
        raise ValueError(f"Unsupported fail-on policy '{fail_on}'.")

    started = utc_now()
    run_id = run_id or new_id()
    revision = _sut_revision()
    if adapter is None:
        adapter = ChatKitAdapter(config.sut)
    if lifecycle is None:
        lifecycle = SutLifecycle(config.sut, adapter)
    trace_store = TraceStore.from_config(config)
    case_results: list[dict[str, Any]] = []
    shutdown_warning: str | None = None
    try:
        await lifecycle.start()
        for case in selected:
            result, trace_path = await _execute_case(
                config, adapter, trace_store, case, run_id=run_id,
                sut_revision=revision,
            )
            case_results.append(_case_document(case, result, trace_path))
    except GateError as exc:
        # Startup/health failure is infrastructure error for all selected cases.
        if not case_results:
            case_results.extend(
                _case_document(case, _error_result(case, run_id, exc), None)
                for case in selected
            )
        else:
            shutdown_warning = f"SUT lifecycle error: {exc.message}"
    finally:
        try:
            await lifecycle.stop()
        except GateError as exc:
            shutdown_warning = f"SUT shutdown error: {exc.message}"
        await adapter.aclose()

    completed = utc_now()
    gate = _gate(case_results, fail_on, infra_error=shutdown_warning)
    report: dict[str, Any] = {
        "run_id": run_id,
        "gate_version": __version__,
        "started_at": started,
        "completed_at": completed,
        "sut_revision": revision,
        "config": config.safe_dict(),
        "model": {
            "provider": config.model.provider,
            "execution_mode": config.model.execution_mode,
            "model_name": _model_name(config),
            "metadata_source": "Gate configuration/environment hint; externally managed SUT settings may differ",
        },
        "comparison_context": _comparison_context(selected, revision, config),
        "summary": _summary(case_results),
        "gate": gate,
        "fail_on": fail_on,
        "cases": case_results,
        "shutdown_warning": shutdown_warning,
        "execution_note": (
            "Execution is serial and each case gets a fresh SUT thread. The SUT uses its configured external model; "
            "deterministic evaluators do not make model generations deterministic. No automatic turn retries are performed."
        ),
    }
    if output:
        base = Path(output)
    else:
        base = config.run.reports_dir / "runs" / run_id
    writer = ReportWriter(
        redact_pii=config.trace.redact_pii,
        max_string_chars=config.trace.max_string_chars,
    )
    json_path, markdown_path = writer.write(base, report)
    return report, json_path, markdown_path


async def _execute_case(
    config: GateConfig,
    adapter: ChatKitAdapter,
    trace_store: TraceStore,
    case: Case,
    *,
    run_id: str,
    sut_revision: str | None,
) -> tuple[CaseResult, Path | None]:
    result = CaseResult(case_id=case.id, run_id=run_id, started_at=utc_now())
    started_clock = time.monotonic()
    session = None
    try:
        session = await asyncio.wait_for(adapter.create_session(), timeout=case.timeout_seconds)
        captures: list[TurnCapture] = []
        for turn_text in case.turns:
            remaining = case.timeout_seconds - (time.monotonic() - started_clock)
            if remaining <= 0:
                raise TraceIncompleteError(f"Case '{case.id}' exceeded its {case.timeout_seconds:g}s timeout.")
            turn = await asyncio.wait_for(adapter.send_turn(session, turn_text), timeout=remaining)
            remaining = case.timeout_seconds - (time.monotonic() - started_clock)
            if remaining <= 0:
                raise TraceIncompleteError(f"Case '{case.id}' exceeded its {case.timeout_seconds:g}s timeout.")
            snapshot = await asyncio.wait_for(adapter.fetch_trace(session), timeout=remaining)
            captures.append(TurnCapture(turn=turn, snapshot=snapshot))

        bundle: TraceBundle = normalize_trace(
            run_id=run_id,
            case_id=case.id,
            captures=captures,
            sut_revision=sut_revision,
            case_version=case.version,
            model_name=_model_name(config),
            execution_mode=config.model.execution_mode,
            require_tool_trace=case.requires_tool_trace,
        )
        bundle.trace.source_limitations.append(
            "Model name/provider are Gate configuration hints; an externally managed SUT may use different model settings."
        )
        result.trace_id = bundle.trace.trace_id
        result.assertions = evaluate_case(case, bundle.trace)
        result.status = (
            ResultStatus.INCOMPLETE
            if bundle.trace.capture_status == "incomplete"
            else ResultStatus.FAIL
            if any(not assertion.passed for assertion in result.assertions)
            else ResultStatus.PASS
        )
        trace_path = trace_store.save(bundle)
        return _finish(result, started_clock), trace_path
    except asyncio.TimeoutError:
        error = TraceIncompleteError(f"Case '{case.id}' exceeded its {case.timeout_seconds:g}s timeout.")
        return _finish(_error_result(case, run_id, error, result=result, status=ResultStatus.INCOMPLETE), started_clock), None
    except GateError as exc:
        status = ResultStatus.INCOMPLETE if exc.category.value == "trace_incomplete" else ResultStatus.ERROR
        return _finish(_error_result(case, run_id, exc, result=result, status=status), started_clock), None
    except Exception as exc:  # Convert implementation/runtime errors to an explicit case error.
        safe = GateError(f"Unexpected case execution error ({type(exc).__name__}).")
        return _finish(_error_result(case, run_id, safe, result=result), started_clock), None
    finally:
        if session is not None:
            await adapter.close_session(session)


def _error_result(
    case: Case,
    run_id: str,
    error: GateError,
    *,
    result: CaseResult | None = None,
    status: ResultStatus = ResultStatus.ERROR,
) -> CaseResult:
    result = result or CaseResult(case_id=case.id, run_id=run_id, started_at=utc_now())
    result.status = status
    result.error_category = error.category.value
    result.error_message = error.message
    return result


def _finish(result: CaseResult, started_clock: float) -> CaseResult:
    result.completed_at = utc_now()
    result.duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    return result


def _case_document(case: Case, result: CaseResult, trace_path: Path | None) -> dict[str, Any]:
    from ..tracing.schema import to_jsonable

    return {
        **to_jsonable(result),
        "name": case.name,
        "description": case.description,
        "base_case_id": case.base_id or case.id,
        "case_version": case.version,
        "parameters": case.parameters,
        "preconditions": case.preconditions,
        "risk_level": case.risk_level,
        "tags": case.tags,
        "trace_path": trace_path.as_posix() if trace_path else None,
    }


def _gate(cases: list[dict[str, Any]], fail_on: str, *, infra_error: str | None = None) -> dict[str, Any]:
    threshold = _FAIL_THRESHOLDS[fail_on]
    critical_failures = sum(
        1 for case in cases for assertion in case["assertions"]
        if not assertion["passed"] and assertion["severity"] == "critical"
    )
    blocking_assertions = sum(
        1 for case in cases for assertion in case["assertions"]
        if not assertion["passed"] and _SEVERITY.get(assertion["severity"], 0) <= threshold
    )
    errors = sum(1 for case in cases if case["status"] == "error") + int(bool(infra_error))
    incomplete = sum(1 for case in cases if case["status"] == "incomplete")
    status = "fail" if blocking_assertions or errors or incomplete else "pass"
    if errors:
        exit_code = 10
    elif incomplete:
        exit_code = 5
    elif blocking_assertions:
        exit_code = 1
    else:
        exit_code = 0
    return {
        "status": status,
        "critical_failures": critical_failures,
        "blocking_assertions": blocking_assertions,
        "errors": errors,
        "incomplete": incomplete,
        "exit_code": exit_code,
    }


def _summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "case_count": len(cases),
        "passed": sum(1 for case in cases if case["status"] == "pass"),
        "failed": sum(1 for case in cases if case["status"] == "fail"),
        "errors": sum(1 for case in cases if case["status"] == "error"),
        "incomplete": sum(1 for case in cases if case["status"] == "incomplete"),
        "assertion_count": sum(len(case["assertions"]) for case in cases),
    }


def _sut_revision() -> str | None:
    value = os.environ.get("GATE_SUT_REVISION")
    if value:
        return value
    lock_path = Path("config/sut.lock.yaml")
    if lock_path.is_file():
        try:
            data = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
            revision = data.get("sut", {}).get("revision") if isinstance(data, dict) else None
            return revision if isinstance(revision, str) else None
        except (OSError, yaml.YAMLError):
            return None
    return None


def _model_name(config: GateConfig) -> str | None:
    if config.model.provider == "deepseek":
        return os.environ.get("DEEPSEEK_MODEL") or os.environ.get("LLM_MODEL") or "deepseek-flash"
    return os.environ.get("LLM_MODEL") or "gpt-5.2"


def _comparison_context(cases: list[Case], revision: str | None, config: GateConfig) -> dict[str, Any]:
    case_document = [
        {
            "id": case.id,
            "version": case.version,
            "turns": case.turns,
            "rules": [
                {"id": rule.id, "type": rule.type, "severity": rule.severity, "params": rule.params}
                for rule in case.rules
            ],
        }
        for case in sorted(cases, key=lambda item: item.id)
    ]
    digest = hashlib.sha256(json.dumps(case_document, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return {
        "case_set_fingerprint": digest,
        "trace_schema_version": 1,
        "evaluator_version": "deterministic-v4",
        "gate_version": __version__,
        "sut_revision": revision,
        "model": {
            "provider": config.model.provider,
            "model_name": _model_name(config),
            "execution_mode": config.model.execution_mode,
        },
    }

