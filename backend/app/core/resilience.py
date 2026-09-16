"""
Resilience utilities for external API calls (Google APIs and Gemini LLM).
Provides bounded exponential backoff with jitter on transient failures (429, 5xx, network timeouts).
Fails fast on non-retryable 401, 403, and 404 errors.
"""
import asyncio
import logging
import random
from typing import Any, Callable, Coroutine, Optional, Set, Type, Union

from googleapiclient.errors import HttpError

from app.core.config import settings

logger = logging.getLogger(settings.PROJECT_NAME)

RETRYABLE_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES: Set[int] = {400, 401, 403, 404, 409, 422}


def get_http_error_status(exc: Exception) -> Optional[int]:
    """Safely extracts HTTP status code from an exception if present."""
    if isinstance(exc, HttpError):
        if hasattr(exc, "resp") and hasattr(exc.resp, "status"):
            return int(exc.resp.status)
        if hasattr(exc, "status_code"):
            return int(exc.status_code)
    if hasattr(exc, "code") and isinstance(exc.code, int):
        return exc.code
    if hasattr(exc, "status") and isinstance(exc.status, int):
        return exc.status
    return None


async def retry_with_backoff(
    operation: Callable[[], Coroutine[Any, Any, Any]],
    operation_name: str = "external_call",
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> Any:
    """
    Executes an async coroutine with bounded exponential backoff and jitter.
    Retries on 429, 5xx, and transient connection/timeout errors.
    Fails fast without retrying on 401, 403, 404.
    """
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:
            attempt += 1
            status_code = get_http_error_status(exc)

            # Fail fast on non-retryable status codes
            if status_code in NON_RETRYABLE_STATUS_CODES:
                logger.warning(
                    "%s encountered non-retryable status %d: %s. Failing fast.",
                    operation_name,
                    status_code,
                    type(exc).__name__,
                )
                raise exc

            # Check if retry limit reached
            if attempt > max_retries:
                logger.error(
                    "%s exceeded maximum retries (%d). Raising exception: %s",
                    operation_name,
                    max_retries,
                    str(exc),
                )
                raise exc

            # Calculate exponential backoff with jitter
            raw_delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0.5, 1.0)
            sleep_duration = raw_delay * jitter

            logger.warning(
                "%s failed on attempt %d/%d (status=%s, exc=%s). Retrying in %.2fs...",
                operation_name,
                attempt,
                max_retries,
                status_code or "none",
                type(exc).__name__,
                sleep_duration,
            )
            await asyncio.sleep(sleep_duration)
