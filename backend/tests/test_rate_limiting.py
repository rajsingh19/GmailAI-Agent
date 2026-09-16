"""
Unit and integration tests for Milestone 9 Distributed Rate Limiting.
Verifies sliding-window enforcement, identity scoping (user_id vs IP),
headers (Retry-After, X-RateLimit-*), concurrency, and fail-closed vs fail-open policies.
"""
import asyncio
import time
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimitResult,
    get_rate_limiter,
    set_rate_limiter_for_testing,
)
from app.core.security import SecurityManager
from app.models.user import User


@pytest.fixture(autouse=True)
def enable_rate_limiting():
    """Activates rate limiting with a clean in-memory rate limiter per test."""
    orig_enabled = settings.RATE_LIMIT_ENABLED
    orig_storage = settings.RATE_LIMIT_STORAGE
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_STORAGE = "memory"
    limiter = InMemoryRateLimiter()
    set_rate_limiter_for_testing(limiter)
    yield limiter
    set_rate_limiter_for_testing(None)
    settings.RATE_LIMIT_ENABLED = orig_enabled
    settings.RATE_LIMIT_STORAGE = orig_storage


@pytest.mark.asyncio
async def test_in_memory_rate_limiter_allows_under_limit(enable_rate_limiting):
    """Requests under quota return allowed=True with decremented remaining count."""
    limiter: InMemoryRateLimiter = enable_rate_limiting
    key = "test_quota_key"
    res1 = await limiter.check_rate_limit(key, max_requests=5, window_seconds=60)
    assert res1.allowed is True
    assert res1.remaining == 4
    assert res1.retry_after == 0

    res2 = await limiter.check_rate_limit(key, max_requests=5, window_seconds=60)
    assert res2.allowed is True
    assert res2.remaining == 3


@pytest.mark.asyncio
async def test_in_memory_rate_limiter_blocks_over_limit_with_retry_after(enable_rate_limiting):
    """Requests exceeding quota return allowed=False and retry_after > 0."""
    limiter: InMemoryRateLimiter = enable_rate_limiting
    key = "test_exceed_key"
    for _ in range(3):
        res = await limiter.check_rate_limit(key, max_requests=3, window_seconds=60)
        assert res.allowed is True

    blocked_res = await limiter.check_rate_limit(key, max_requests=3, window_seconds=60)
    assert blocked_res.allowed is False
    assert blocked_res.remaining == 0
    assert blocked_res.retry_after > 0


@pytest.mark.asyncio
async def test_unauthenticated_request_rate_limited_by_ip(async_client: AsyncClient):
    """Unauthenticated requests are tracked and limited by client IP."""
    orig_auth_limit = settings.RATE_LIMIT_AUTH_LIMIT
    try:
        settings.RATE_LIMIT_AUTH_LIMIT = 2
        # First 2 requests to /auth/status succeed
        resp1 = await async_client.get("/auth/status")
        assert resp1.status_code == 200
        resp2 = await async_client.get("/auth/status")
        assert resp2.status_code == 200

        # 3rd request hits 429
        resp3 = await async_client.get("/auth/status")
        assert resp3.status_code == 429
        data = resp3.json()
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in resp3.headers
    finally:
        settings.RATE_LIMIT_AUTH_LIMIT = orig_auth_limit


@pytest.mark.asyncio
async def test_authenticated_request_rate_limited_by_user_id(async_client: AsyncClient, test_db: AsyncSession):
    """Authenticated requests are scoped by user_id, not IP."""
    user = User(
        email="ratelimit_user@example.com",
        full_name="Rate Limit User",
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)

    token = SecurityManager.create_session_token(user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)

    orig_default_limit = settings.RATE_LIMIT_DEFAULT_LIMIT
    try:
        settings.RATE_LIMIT_DEFAULT_LIMIT = 3
        for _ in range(3):
            resp = await async_client.get("/api/v1/tasks")
            assert resp.status_code == 200

        # 4th request must be 429
        blocked = await async_client.get("/api/v1/tasks")
        assert blocked.status_code == 429
    finally:
        settings.RATE_LIMIT_DEFAULT_LIMIT = orig_default_limit


@pytest.mark.asyncio
async def test_user_a_and_user_b_have_independent_quotas(async_client: AsyncClient, test_db: AsyncSession):
    """Exhausting quota for User A does not affect User B's quota."""
    user_a = User(email="user_a_quota@example.com", full_name="User A", is_active=True)
    user_b = User(email="user_b_quota@example.com", full_name="User B", is_active=True)
    test_db.add_all([user_a, user_b])
    await test_db.commit()
    await test_db.refresh(user_a)
    await test_db.refresh(user_b)

    orig_limit = settings.RATE_LIMIT_DEFAULT_LIMIT
    try:
        settings.RATE_LIMIT_DEFAULT_LIMIT = 2

        # Exhaust User A
        token_a = SecurityManager.create_session_token(user_a.id)
        async_client.cookies.set(settings.SESSION_COOKIE_NAME, token_a)
        await async_client.get("/api/v1/tasks")
        await async_client.get("/api/v1/tasks")
        resp_a_blocked = await async_client.get("/api/v1/tasks")
        assert resp_a_blocked.status_code == 429

        # User B makes requests and succeeds
        token_b = SecurityManager.create_session_token(user_b.id)
        async_client.cookies.set(settings.SESSION_COOKIE_NAME, token_b)
        resp_b = await async_client.get("/api/v1/tasks")
        assert resp_b.status_code == 200
    finally:
        settings.RATE_LIMIT_DEFAULT_LIMIT = orig_limit


@pytest.mark.asyncio
async def test_security_endpoint_fails_closed_when_rate_limiter_errors(async_client: AsyncClient):
    """
    CRITICAL SECURITY TEST:
    When rate limiter storage errors occur on security-critical endpoints
    (/auth/* and /api/v1/proactive/actions/execute), endpoints fail CLOSED (HTTP 503).
    """
    from app.core.rate_limit import is_security_critical_endpoint

    # Verify classification logic explicitly
    assert is_security_critical_endpoint("/auth/google") is True
    assert is_security_critical_endpoint("/auth/callback") is True
    assert is_security_critical_endpoint("/auth/session") is True
    assert is_security_critical_endpoint("/api/v1/proactive/actions/execute") is True
    assert is_security_critical_endpoint("/api/v1/agent/chat") is False
    assert is_security_critical_endpoint("/api/v1/tasks") is False

    class BrokenLimiter(InMemoryRateLimiter):
        async def check_rate_limit(self, key, max_requests, window_seconds):
            raise ConnectionError("Redis cluster connection timeout")

    set_rate_limiter_for_testing(BrokenLimiter())

    # Security endpoint /auth/callback fails closed
    resp = await async_client.get("/auth/callback?code=abc&state=xyz")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    # Security endpoint /api/v1/proactive/actions/execute fails closed
    resp_action = await async_client.post("/api/v1/proactive/actions/execute", json={})
    assert resp_action.status_code == 503
    assert resp_action.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_standard_endpoint_fails_open_with_warning_when_rate_limiter_errors(
    async_client: AsyncClient, test_db: AsyncSession
):
    """
    When rate limiter storage errors occur on standard endpoints (/api/v1/tasks, /api/v1/agent/*),
    endpoints fail OPEN to preserve service availability.
    """
    class BrokenLimiter(InMemoryRateLimiter):
        async def check_rate_limit(self, key, max_requests, window_seconds):
            raise ConnectionError("Redis cluster connection timeout")

    set_rate_limiter_for_testing(BrokenLimiter())

    user = User(email="failopen@example.com", full_name="User", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)

    token = SecurityManager.create_session_token(user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)

    resp = await async_client.get("/api/v1/tasks")
    # Allowed to proceed (fail open)
    assert resp.status_code == 200

    # Agent endpoints also fail open through rate limiter to downstream handler
    resp_agent = await async_client.get("/api/v1/agent/tools")
    assert resp_agent.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_headers_present_on_allowed_requests(async_client: AsyncClient):
    """Successful requests include X-RateLimit-Limit, Remaining, and Reset headers."""
    resp = await async_client.get("/auth/status")
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert "X-RateLimit-Reset" in resp.headers


@pytest.mark.asyncio
async def test_rate_limit_429_returns_retry_after_and_standard_error_payload(async_client: AsyncClient):
    """HTTP 429 response includes Retry-After header and M9 error JSON payload."""
    orig_limit = settings.RATE_LIMIT_AUTH_LIMIT
    try:
        settings.RATE_LIMIT_AUTH_LIMIT = 1
        await async_client.get("/auth/status")
        resp = await async_client.get("/auth/status")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        data = resp.json()
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry_after" in data["error"]["details"]
    finally:
        settings.RATE_LIMIT_AUTH_LIMIT = orig_limit


@pytest.mark.asyncio
async def test_exempt_endpoints_never_rate_limited(async_client: AsyncClient):
    """Health and metrics probes are exempt from rate limiting."""
    for _ in range(20):
        resp = await async_client.get("/health")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_requests_atomic_rate_limiting(enable_rate_limiting):
    """10 concurrent requests with limit 5 results in exactly 5 allowed and 5 blocked."""
    limiter = enable_rate_limiting
    key = "concurrent_test_key"
    limit = 5

    async def _attempt():
        return await limiter.check_rate_limit(key, max_requests=limit, window_seconds=60)

    results = await asyncio.gather(*[_attempt() for _ in range(10)])
    allowed_count = sum(1 for r in results if r.allowed)
    blocked_count = sum(1 for r in results if not r.allowed)

    assert allowed_count == 5
    assert blocked_count == 5


@pytest.mark.asyncio
async def test_sliding_window_resets_after_window_expires(enable_rate_limiting):
    """After sliding window expires, quota is completely restored."""
    limiter = enable_rate_limiting
    key = "expiry_test_key"
    limit = 2
    window = 1  # 1 second window

    res1 = await limiter.check_rate_limit(key, max_requests=limit, window_seconds=window)
    res2 = await limiter.check_rate_limit(key, max_requests=limit, window_seconds=window)
    res3 = await limiter.check_rate_limit(key, max_requests=limit, window_seconds=window)
    assert res1.allowed is True
    assert res2.allowed is True
    assert res3.allowed is False

    # Wait for window to expire
    await asyncio.sleep(1.1)

    res4 = await limiter.check_rate_limit(key, max_requests=limit, window_seconds=window)
    assert res4.allowed is True
    assert res4.remaining == 1

