"""
Tests for Voice Endpoint Rate Limiting and Quota Enforcement (Milestone 10).
Verifies:
- get_endpoint_policy returns the ("voice", limit, window) policy for /api/v1/voice/*
- Voice endpoints under limit are allowed with rate limit headers
- Voice requests exceeding limit are blocked with HTTP 429 and Retry-After header
- Multi-user isolation: User A and User B have independent voice quotas
- Sliding window resets after window expires
- Standard X-RateLimit-* headers are present on voice responses
"""

import time
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    get_endpoint_policy,
    set_rate_limiter_for_testing,
)
from app.core.security import SecurityManager
from app.models.user import User
from app.voice.providers.factory import set_tts_provider_for_testing
from app.voice.providers.mock_tts import MockTTSProvider


async def create_test_user(test_db: AsyncSession, email: str = "voice_rate_user@example.com") -> User:
    user = User(email=email, full_name="Voice Rate Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.fixture
def enable_voice_rate_limiting():
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


def test_voice_rate_limit_policy_returns_correct_quota():
    bucket, limit, window = get_endpoint_policy("/api/v1/voice/transcribe")
    assert bucket == "voice"
    assert limit == settings.RATE_LIMIT_VOICE_LIMIT
    assert window == settings.RATE_LIMIT_VOICE_WINDOW

    bucket_synth, limit_synth, window_synth = get_endpoint_policy("/api/v1/voice/synthesize")
    assert bucket_synth == "voice"

    bucket_chat, limit_chat, window_chat = get_endpoint_policy("/api/v1/voice/chat")
    assert bucket_chat == "voice"


@pytest.mark.asyncio
async def test_voice_endpoints_under_limit_allowed(enable_voice_rate_limiting, async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_under_limit@example.com")
    set_auth_cookie(async_client, user)

    set_tts_provider_for_testing(MockTTSProvider())
    try:
        payload = {"text": "Under quota speech"}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 200
        assert "x-ratelimit-limit" in res.headers
        assert "x-ratelimit-remaining" in res.headers
    finally:
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_endpoints_over_limit_blocked_with_429(enable_voice_rate_limiting, async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_over_limit@example.com")
    set_auth_cookie(async_client, user)

    set_tts_provider_for_testing(MockTTSProvider())
    try:
        # Lower limit for quick exhaustion
        orig_limit = settings.RATE_LIMIT_VOICE_LIMIT
        settings.RATE_LIMIT_VOICE_LIMIT = 3

        payload = {"text": "Speech test"}
        for _ in range(3):
            r = await async_client.post("/api/v1/voice/synthesize", json=payload)
            assert r.status_code == 200

        # 4th request must be rate limited
        r_blocked = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert r_blocked.status_code == 429
        assert "retry-after" in r_blocked.headers
        data = r_blocked.json()
        assert "too many requests" in data["detail"].lower() or "rate limit" in data["detail"].lower()
    finally:
        settings.RATE_LIMIT_VOICE_LIMIT = orig_limit
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_independent_quotas_for_user_a_and_user_b(enable_voice_rate_limiting, async_client: AsyncClient, test_db: AsyncSession):
    user_a = await create_test_user(test_db, "voice_user_a_rate@example.com")
    user_b = await create_test_user(test_db, "voice_user_b_rate@example.com")

    set_tts_provider_for_testing(MockTTSProvider())
    try:
        orig_limit = settings.RATE_LIMIT_VOICE_LIMIT
        settings.RATE_LIMIT_VOICE_LIMIT = 2

        payload = {"text": "Quota test"}

        # Exhaust User A's quota
        set_auth_cookie(async_client, user_a)
        await async_client.post("/api/v1/voice/synthesize", json=payload)
        await async_client.post("/api/v1/voice/synthesize", json=payload)
        r_blocked = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert r_blocked.status_code == 429

        # User B should still be allowed
        set_auth_cookie(async_client, user_b)
        r_user_b = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert r_user_b.status_code == 200
    finally:
        settings.RATE_LIMIT_VOICE_LIMIT = orig_limit
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_sliding_window_resets_after_window_expires(enable_voice_rate_limiting):
    limiter: InMemoryRateLimiter = enable_voice_rate_limiting
    key = "voice_sliding_window_key"

    # Fill quota of 2 in 1 second window
    res1 = await limiter.check_rate_limit(key, max_requests=2, window_seconds=1)
    assert res1.allowed is True
    res2 = await limiter.check_rate_limit(key, max_requests=2, window_seconds=1)
    assert res2.allowed is True

    # Over quota
    res_blocked = await limiter.check_rate_limit(key, max_requests=2, window_seconds=1)
    assert res_blocked.allowed is False

    # Wait for window to expire
    import asyncio
    await asyncio.sleep(1.05)

    # Allowed again
    res_fresh = await limiter.check_rate_limit(key, max_requests=2, window_seconds=1)
    assert res_fresh.allowed is True
    assert res_fresh.remaining == 1


@pytest.mark.asyncio
async def test_voice_rate_limit_headers_present(enable_voice_rate_limiting, async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_headers_check@example.com")
    set_auth_cookie(async_client, user)

    set_tts_provider_for_testing(MockTTSProvider())
    try:
        payload = {"text": "Checking rate limit headers"}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 200
        assert "x-ratelimit-limit" in res.headers
        assert "x-ratelimit-remaining" in res.headers
        assert "x-ratelimit-reset" in res.headers
    finally:
        set_tts_provider_for_testing(None)
