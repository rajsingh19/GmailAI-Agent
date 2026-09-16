"""
Unit tests for Milestone 9 Google API and Gemini Resilience with Retry Safety.
Verifies bounded exponential backoff with jitter on 429/5xx, fast failure on 401/403/404,
and preservation of strict read-only guarantees.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from googleapiclient.errors import HttpError
import httpx

from app.core.resilience import (
    NON_RETRYABLE_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    get_http_error_status,
    retry_with_backoff,
)


def _make_http_error(status_code: int, reason: str = "Error") -> HttpError:
    """Helper to construct googleapiclient HttpError with specific status code."""
    resp = httpx.Response(status_code=status_code, request=httpx.Request("GET", "https://example.com"))
    mock_resp = MagicMock()
    mock_resp.status = status_code
    mock_resp.reason = reason
    return HttpError(resp=mock_resp, content=b"{}")


@pytest.mark.asyncio
async def test_retry_with_backoff_succeeds_first_try():
    """Successful operation returns immediately without retrying."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        return "success_val"

    res = await retry_with_backoff(op, operation_name="test_op", max_retries=3)
    assert res == "success_val"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_transient_429():
    """Transient rate limit (HTTP 429) is retried with backoff and succeeds."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _make_http_error(429, "Rate Limit Exceeded")
        return "rate_limit_recovered"

    res = await retry_with_backoff(
        op, operation_name="test_429", max_retries=3, base_delay=0.01, max_delay=0.05
    )
    assert res == "rate_limit_recovered"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_transient_503():
    """Transient server error (HTTP 503) is retried and succeeds."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise _make_http_error(503, "Service Unavailable")
        return "server_recovered"

    res = await retry_with_backoff(
        op, operation_name="test_503", max_retries=3, base_delay=0.01, max_delay=0.05
    )
    assert res == "server_recovered"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_with_backoff_fails_fast_on_401():
    """Authentication required (HTTP 401) fails immediately without retry storm."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        raise _make_http_error(401, "Unauthorized")

    with pytest.raises(HttpError) as exc_info:
        await retry_with_backoff(op, operation_name="test_401", max_retries=3)

    assert exc_info.value.resp.status == 401
    assert call_count == 1  # Exactly 1 call; no retries


@pytest.mark.asyncio
async def test_retry_with_backoff_fails_fast_on_403():
    """Forbidden/Scope missing (HTTP 403) fails immediately without retrying."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        raise _make_http_error(403, "Forbidden")

    with pytest.raises(HttpError):
        await retry_with_backoff(op, operation_name="test_403", max_retries=3)

    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_with_backoff_fails_fast_on_404():
    """Resource not found (HTTP 404) fails immediately without retrying."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        raise _make_http_error(404, "Not Found")

    with pytest.raises(HttpError):
        await retry_with_backoff(op, operation_name="test_404", max_retries=3)

    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_with_backoff_exceeds_max_retries_raises():
    """Persistent 500 error exceeds max_retries and raises exception."""
    call_count = 0

    async def op():
        nonlocal call_count
        call_count += 1
        raise _make_http_error(500, "Internal Error")

    with pytest.raises(HttpError):
        await retry_with_backoff(
            op, operation_name="test_persistent", max_retries=2, base_delay=0.01, max_delay=0.05
        )

    assert call_count == 3  # Initial try + 2 retries = 3 total attempts


def test_gmail_calendar_strictly_read_only_invariants():
    """Verifies that GmailService and CalendarService do not expose write/delete methods."""
    from app.services.gmail_service import GmailService
    from app.services.calendar_service import CalendarService

    # Check that write methods are absent
    forbidden_gmail_methods = [
        "send_message",
        "create_draft",
        "delete_message",
        "trash_message",
        "modify_labels",
    ]
    for m in forbidden_gmail_methods:
        assert not hasattr(GmailService, m), f"GmailService must remain strictly read-only; {m} found"

    forbidden_cal_methods = [
        "create_event",
        "update_event",
        "delete_event",
        "patch_event",
        "insert_calendar",
    ]
    for m in forbidden_cal_methods:
        assert not hasattr(CalendarService, m), f"CalendarService must remain strictly read-only; {m} found"
