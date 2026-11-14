from __future__ import annotations

import pytest

from agent_regression_gate.tracing.redaction import TraceRedactor


def test_redacts_pii_and_secret_keys_without_touching_plain_fields():
    redactor = TraceRedactor(redact_pii=True)
    value = redactor.redact(
        {
            "passenger_name": "Morgan Lee",
            "confirmation_number": "IR-D204",
            "flight_number": "PA441",
            "api_key": "sk-live-secret",
            "nested": {"account_number": "A-123", "seat": "14C"},
        }
    )
    assert value["passenger_name"] == "[REDACTED]"
    assert value["confirmation_number"] == "[REDACTED]"
    assert value["flight_number"] == "PA441"
    assert value["api_key"] == "[REDACTED]"
    assert value["nested"] == {"account_number": "[REDACTED]", "seat": "14C"}
    assert redactor.stats.fields_redacted >= 4


def test_redacts_email_and_phone_inside_text():
    redactor = TraceRedactor(redact_pii=True)
    value = redactor.redact(
        {
            "note": "Email morgan@example.com or call +1 (415) 555-2671.",
            "phone": "+1 (415) 555-2671",
        }
    )
    assert "morgan@example.com" not in value["note"]
    assert "555-2671" not in value["note"]
    assert value["phone"] == "[REDACTED]"


def test_strips_url_query_and_fragment():
    redactor = TraceRedactor(redact_pii=True)
    value = redactor.redact({"url": "https://example.test/a?token=secret&x=1#frag"})
    assert value["url"] == "https://example.test/a"


def test_truncates_long_strings():
    redactor = TraceRedactor(redact_pii=True, max_string_chars=10)
    value = redactor.redact({"text": "x" * 20})
    assert value["text"].startswith("x" * 10)
    assert value["text"].endswith("[TRUNCATED]")
    assert redactor.stats.values_truncated == 1


def test_secret_values_are_redacted_even_when_pii_redaction_is_disabled():
    redactor = TraceRedactor(redact_pii=False)
    value = redactor.redact({"note": "Authorization: Bearer abc.def", "confirmation_number": "IR-D204"})
    assert value["confirmation_number"] == "IR-D204"
    assert "Bearer" not in value["note"]


def test_pii_key_with_none_value_stays_none():
    redactor = TraceRedactor(redact_pii=True)
    assert redactor.redact(None, key="confirmation_number") is None
    assert redactor.stats.fields_redacted == 0
    assert redactor.redact({"confirmation_number": None, "seat": "14C"}) == {
        "confirmation_number": None,
        "seat": "14C",
    }
