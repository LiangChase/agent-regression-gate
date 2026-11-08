"""Versioned, sanitized JSON and Markdown run reports."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import TraceStorageError
from ..tracing.redaction import TraceRedactor
from ..tracing.schema import to_jsonable

REPORT_SCHEMA_VERSION = 1


class ReportWriter:
    def __init__(self, *, redact_pii: bool = True, max_string_chars: int = 4000) -> None:
        self.redact_pii = redact_pii
        self.max_string_chars = max_string_chars

    def write(self, base_path: str | Path, report: dict[str, Any]) -> tuple[Path, Path]:
        base = Path(base_path)
        if base.suffix.lower() in {".json", ".md", ".markdown"}:
            base = base.with_suffix("")
        json_path, markdown_path = base.with_suffix(".json"), base.with_suffix(".md")
        payload = dict(report)
        payload["report_schema_version"] = REPORT_SCHEMA_VERSION
        redactor = TraceRedactor(redact_pii=self.redact_pii, max_string_chars=self.max_string_chars)
        safe_report = redactor.redact(to_jsonable(payload))
        safe_report["redaction_summary"] = redactor.stats.to_dict()
        try:
            encoded = json.dumps(safe_report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            markdown = render_markdown(safe_report)
            _atomic_write(json_path, encoded)
            _atomic_write(markdown_path, markdown.encode("utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise TraceStorageError("Run report could not be written safely.") from exc
        return json_path, markdown_path


def render_markdown(report: dict[str, Any]) -> str:
    gate = report.get("gate", {})
    status = str(gate.get("status", "unknown")).upper()
    cases = report.get("cases", [])
    failed = [case for case in cases if case.get("status") in {"fail", "error", "incomplete"}]
    lines = [
        f"# Agent Regression Gate — {status}",
        "",
        f"- Run: `{report.get('run_id', 'unknown')}`",
        f"- Started: {report.get('started_at', '')}",
        f"- Completed: {report.get('completed_at', '')}",
        f"- SUT revision: `{report.get('sut_revision') or 'unknown'}`",
        f"- Cases: {report.get('summary', {}).get('case_count', 0)}",
        f"- Gate policy: fail on `{report.get('fail_on', 'critical')}` assertions; infrastructure errors always block.",
        "",
    ]
    if failed:
        lines.extend(["## Failures and infrastructure issues", ""])
        for case in failed:
            lines.append(f"### {case.get('case_id')} — {case.get('name', '')} ({str(case.get('status')).upper()})")
            if case.get("error_message"):
                lines.append(f"- Error: {case['error_message']} ({case.get('error_category') or 'unknown'})")
            for assertion in case.get("assertions", []):
                if assertion.get("passed"):
                    continue
                lines.append(f"- [{str(assertion.get('severity', 'critical')).upper()}] `{assertion.get('assertion_id')}` {assertion.get('message', '')}")
                lines.append(f"  Expected: `{_compact(assertion.get('expected'))}`")
                lines.append(f"  Actual: `{_compact(assertion.get('actual'))}`")
                if assertion.get("evidence_event_ids"):
                    lines.append(f"  Evidence events: `{', '.join(assertion['evidence_event_ids'])}`")
            if case.get("trace_path"):
                lines.append(f"- Trace: `{case['trace_path']}`")
            lines.append("")
    lines.extend(["## Case results", "", "| Case | Risk | Status | Assertions | Duration | Trace |", "|---|---|---:|---:|---:|---|"])
    for case in cases:
        assertions = case.get("assertions", [])
        passed = sum(1 for item in assertions if item.get("passed"))
        trace = f"`{case.get('trace_path')}`" if case.get("trace_path") else "—"
        duration = case.get("duration_ms")
        duration_text = f"{duration:.0f} ms" if isinstance(duration, (int, float)) else "—"
        lines.append(f"| {case.get('case_id')} | {case.get('risk_level', '—')} | {str(case.get('status', 'unknown')).upper()} | {passed}/{len(assertions)} | {duration_text} | {trace} |")
    lines.extend(["", "## Gate summary", "", f"- Result: **{status}**", f"- Critical failures: {gate.get('critical_failures', 0)}", f"- Errors: {gate.get('errors', 0)}", f"- Incomplete cases: {gate.get('incomplete', 0)}", f"- Exit code: `{gate.get('exit_code', 10)}`", ""])
    if report.get("execution_note"):
        lines.extend(["## Execution note", "", report["execution_note"], ""])
    if report.get("shutdown_warning"):
        lines.extend(["## Lifecycle warning", "", report["shutdown_warning"], ""])
    lines.extend(["## Reproducibility context", "", f"- Gate-configured provider: `{report.get('model', {}).get('provider', 'unknown')}`", f"- Configured mode: `{report.get('model', {}).get('execution_mode', 'unknown')}`", f"- Metadata source: {report.get('model', {}).get('metadata_source', 'not recorded')}", "- Deterministic evaluators inspect recorded events and do not make an external model response deterministic.", ""])
    return "\n".join(lines)


def _compact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= 220 else text[:217] + "..."


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise

