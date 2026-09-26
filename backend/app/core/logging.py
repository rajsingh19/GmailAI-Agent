import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.config import settings
from app.core.context import get_request_id, get_user_id

# Regex patterns for sensitive data masking
_PATTERNS = [
    (re.compile(r"ya29\.[a-zA-Z0-9_\-\.]+"), "[REDACTED_GOOGLE_TOKEN]"),
    (re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]+"), r"\1[REDACTED_BEARER_TOKEN]"),
    (re.compile(r"(client_secret=)[^&\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("client_secret"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
    (re.compile(r"(password=)[^&\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("password"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
    (re.compile(r"(token_encryption_key=)[^&\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("token_encryption_key"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
    (re.compile(r"(api_key=)[^&\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("api_key"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
    (re.compile(r"(auth_token=)[^&\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("auth_token"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
    (re.compile(r"(api_secret=)[^&\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("api_secret"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
]


def redact_sensitive_text(text: str) -> str:
    """Applies sensitive data redaction regexes to arbitrary text."""
    if not isinstance(text, str):
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that masks sensitive tokens, passwords, and secrets from log messages
    and attaches request_id/user_id from contextvars.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_sensitive_text(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    redact_sensitive_text(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        # Attach contextvar request_id and user_id to the record
        if not hasattr(record, "request_id") or not record.request_id:
            record.request_id = get_request_id() or "-"
        if not hasattr(record, "user_id") or not record.user_id:
            record.user_id = get_user_id() or "-"

        return True


class StructuredJsonFormatter(logging.Formatter):
    """
    Emits single-line JSON log objects suitable for Elasticsearch, CloudWatch, Datadog.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    """
    Configures structured logging for the application.
    Supports standard human-readable text (dev) and structured JSON (prod).
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    use_json = settings.LOG_FORMAT == "json" or settings.ENVIRONMENT == "production"

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveDataFilter())

    if use_json:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        text_format = (
            "%(asctime)s | %(levelname)-8s | [%(request_id)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
        )
        handler.setFormatter(logging.Formatter(text_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]

    # Suppress verbose third-party loggers if needed
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    logger_inst = logging.getLogger(settings.PROJECT_NAME)
    logger_inst.setLevel(log_level)
    return logger_inst


logger = setup_logging()
