"""Structured logging with context fields and defensive secret redaction."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_run_id: ContextVar[str | None] = ContextVar("gate_run_id", default=None)
_case_id: ContextVar[str | None] = ContextVar("gate_case_id", default=None)
_SECRET_TEXT = re.compile(
    r"(?i)(\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,})\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]+=*|"
    r"\b(?:api[_-]?key|secret|token|password|authorization)\s*[=:]\s*[^\s,;&]+)"
)


def redact_text(value: str) -> str:
    return _SECRET_TEXT.sub("[REDACTED]", value)


def redact_value(value: Any, *, key: str = "") -> Any:
    if re.search(r"(?i)(api.?key|secret|token|password|authorization|credential)", key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        if "url" in key.lower():
            try:
                parts = urlsplit(value)
                if parts.scheme and parts.netloc:
                    host = parts.hostname or ""
                    if parts.port:
                        host = f"{host}:{parts.port}"
                    value = urlunsplit((parts.scheme, host, parts.path, "", ""))
            except ValueError:
                value = "[invalid-url]"
        return redact_text(value)
    return value


def bind_context(*, run_id: str | None = None, case_id: str | None = None) -> tuple[Any, Any]:
    """Set correlation IDs for the current async/task context; return reset tokens."""
    return _run_id.set(run_id), _case_id.set(case_id)


def reset_context(tokens: tuple[Any, Any]) -> None:
    _run_id.reset(tokens[0])
    _case_id.reset(tokens[1])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "run_id": _run_id.get(),
            "case_id": _case_id.get(),
        }
        for field in ("duration_ms", "sut_url", "error_category", "event"):
            if hasattr(record, field):
                payload[field] = redact_value(getattr(record, field), key=field)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        record.case_id = _case_id.get()
        return True


class ContextTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        return super().format(record)


def configure_logging(level: str = "INFO", output_format: str = "json") -> logging.Logger:
    logger = logging.getLogger("agent_regression_gate")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    if output_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            ContextTextFormatter("%(asctime)s %(levelname)s run=%(run_id)s case=%(case_id)s %(message)s")
        )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
