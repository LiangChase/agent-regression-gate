"""Shared, safe error taxonomy for the CLI and execution pipeline."""

from __future__ import annotations

from enum import StrEnum
import re


class ErrorCategory(StrEnum):
    CONFIGURATION = "configuration_error"
    SUT_UNAVAILABLE = "sut_unavailable"
    PROTOCOL = "protocol_error"
    TRACE_INCOMPLETE = "trace_incomplete"
    ASSERTION_FAILURE = "assertion_failure"
    STORAGE = "storage_error"
    INTERNAL = "internal_error"


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(
        r"(?i)(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
        r"Bearer\s+[A-Za-z0-9._~+/-]+=*)",
        "[REDACTED]",
        value,
    )
    return re.sub(
        r"(?i)(api[_-]?key|secret|token|password|authorization)\s*[=:]\s*[^\s,;&]+",
        r"\1=[REDACTED]",
        value,
    )


class GateError(Exception):
    """Base exception carrying a stable category and safe user-facing message."""

    category = ErrorCategory.INTERNAL
    exit_code = 10

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        self.message = _safe_text(message) or ""
        self.detail = _safe_text(detail)
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "category": self.category.value,
            "message": self.message,
            "detail": self.detail,
        }


class ConfigurationError(GateError):
    category = ErrorCategory.CONFIGURATION
    exit_code = 2


class SutUnavailableError(GateError):
    category = ErrorCategory.SUT_UNAVAILABLE
    exit_code = 3


class ProtocolError(GateError):
    category = ErrorCategory.PROTOCOL
    exit_code = 4


class TraceIncompleteError(GateError):
    category = ErrorCategory.TRACE_INCOMPLETE
    exit_code = 5


class AssertionFailure(GateError):
    category = ErrorCategory.ASSERTION_FAILURE
    exit_code = 1


class TraceStorageError(GateError):
    category = ErrorCategory.STORAGE
    exit_code = 11
