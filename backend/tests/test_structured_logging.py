"""
Unit tests for Milestone 9 Structured Logging and Sensitive Data Redaction.
Validates JSON formatting and automated redaction of tokens, passwords, and secrets.
"""
import json
import logging
import pytest

from app.core.context import set_request_id, set_user_id
from app.core.logging import (
    SensitiveDataFilter,
    StructuredJsonFormatter,
    redact_sensitive_text,
)


def test_redact_sensitive_text_google_oauth_token():
    """OAuth access tokens (ya29...) must be redacted."""
    raw = "User logged in with token ya29.a0AfH6SMD_test_token_12345 successfully"
    redacted = redact_sensitive_text(raw)
    assert "ya29" not in redacted
    assert "[REDACTED_GOOGLE_TOKEN]" in redacted


def test_redact_sensitive_text_bearer_token():
    """Bearer authorization tokens must be redacted."""
    raw = "Header Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    redacted = redact_sensitive_text(raw)
    assert "eyJhbGci" not in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted


def test_redact_sensitive_text_client_secret():
    """Client secrets in query strings or JSON must be redacted."""
    raw1 = "Config loaded with client_secret=GOCSPX-super_secret_12345 and other params"
    redacted1 = redact_sensitive_text(raw1)
    assert "GOCSPX" not in redacted1
    assert "client_secret=[REDACTED]" in redacted1

    raw2 = '{"client_id": "my_id", "client_secret": "GOCSPX-hidden_secret_value"}'
    redacted2 = redact_sensitive_text(raw2)
    assert "hidden_secret_value" not in redacted2


def test_redact_sensitive_text_password():
    """Passwords in strings or key-values must be redacted."""
    raw = "Connecting to database with password=super_secret_db_pass_987"
    redacted = redact_sensitive_text(raw)
    assert "super_secret_db_pass_987" not in redacted
    assert "password=[REDACTED]" in redacted


def test_redact_sensitive_text_api_key():
    """API keys must be redacted."""
    raw = "Initialized Gemini with api_key=AIzaSyD_my_secret_gemini_key_123"
    redacted = redact_sensitive_text(raw)
    assert "AIzaSyD_my_secret_gemini_key_123" not in redacted
    assert "api_key=[REDACTED]" in redacted


def test_structured_json_formatter_fields():
    """StructuredJsonFormatter must produce valid JSON with all required fields."""
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test message for structured logging",
        args=(),
        exc_info=None,
    )
    record.request_id = "req_test_123456"
    record.user_id = "usr_test_987"

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["message"] == "Test message for structured logging"
    assert data["request_id"] == "req_test_123456"
    assert data["user_id"] == "usr_test_987"
    assert "timestamp" in data
    assert data["line"] == 42


def test_sensitive_data_filter_masks_log_record_message_and_args():
    """SensitiveDataFilter must redact both msg and formatted args."""
    flt = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.WARNING,
        pathname="test.py",
        lineno=10,
        msg="Found token %s for user",
        args=("ya29.sample_oauth_token_val",),
        exc_info=None,
    )
    flt.filter(record)
    assert "ya29" not in record.args[0]
    assert "[REDACTED_GOOGLE_TOKEN]" in record.args[0]


def test_logging_includes_request_id_from_contextvar():
    """Log filter must automatically inject request_id and user_id from contextvars."""
    set_request_id("req_ctx_abc123")
    set_user_id("usr_ctx_xyz789")

    flt = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=15,
        msg="Action performed",
        args=(),
        exc_info=None,
    )
    flt.filter(record)

    assert record.request_id == "req_ctx_abc123"
    assert record.user_id == "usr_ctx_xyz789"
