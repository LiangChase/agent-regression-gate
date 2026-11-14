"""Privacy and size controls applied before trace data reaches disk or reports."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


_SECRET_VALUE = re.compile(
    r"(?i)(\bsk-[A-Za-z0-9_-]{12,}\b|\bgh[pousr]_[A-Za-z0-9_]{20,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]+=*)"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]?\d{4}(?!\w)")
_SECRET_KEY = re.compile(r"(?i)(?:api.?key|secret|token|password|authorization|credential)")
_PII_KEY = re.compile(
    r"(?i)(?:passenger.?name|confirmation.?number|account.?number|email|phone|mobile|"
    r"birth.?date|street.?address|special.?service.?note|thread.?id|request.?id)"
)


@dataclass(slots=True)
class RedactionStats:
    fields_redacted: int = 0
    text_matches_redacted: int = 0
    values_truncated: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class TraceRedactor:
    def __init__(self, *, redact_pii: bool = True, max_string_chars: int = 4000) -> None:
        if max_string_chars < 1:
            raise ValueError("max_string_chars must be greater than zero")
        self.redact_pii = redact_pii
        self.max_string_chars = max_string_chars
        self.stats = RedactionStats()

    def redact(self, value: Any, *, key: str = "") -> Any:
        if value is not None and (_SECRET_KEY.search(key) or (self.redact_pii and _PII_KEY.search(key))):
            self.stats.fields_redacted += 1
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {str(item_key): self.redact(item, key=str(item_key)) for item_key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            return self._redact_text(value, key)
        return value

    def _redact_text(self, value: str, key: str) -> str:
        if "url" in key.lower():
            value = _strip_url_secrets(value)
        value = self._replace(_SECRET_VALUE, value)
        if self.redact_pii:
            value = self._replace(_EMAIL, value)
            if "phone" in key.lower() or "mobile" in key.lower():
                value = "[REDACTED]"
            else:
                value = self._replace(_PHONE, value)
        if len(value) > self.max_string_chars:
            value = value[: self.max_string_chars] + "…[TRUNCATED]"
            self.stats.values_truncated += 1
        return value

    def _replace(self, pattern: re.Pattern[str], value: str) -> str:
        replaced, count = pattern.subn("[REDACTED]", value)
        self.stats.text_matches_redacted += count
        return replaced


def _strip_url_secrets(value: str) -> str:
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return value
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return "[invalid-url]"
