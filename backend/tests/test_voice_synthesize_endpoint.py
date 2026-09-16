"""
Tests for Voice Speech Synthesis Endpoint (POST /api/v1/voice/synthesize).
Verifies:
- 401 Unauthorized for unauthenticated requests
- 200 OK returning binary audio stream with Content-Type: audio/wav
- 422 Unprocessable Entity on empty text input
- 422 Unprocessable Entity on oversized text input (> 1000 chars)
- Correct voice and language parameter handling
- 504 Gateway Timeout on provider timeout
- 429 Too Many Requests on provider rate limit
- 502 Bad Gateway on provider failure
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.voice.providers.factory import set_tts_provider_for_testing
from app.voice.providers.mock_tts import MockTTSProvider


async def create_test_user(test_db: AsyncSession, email: str = "voice_synth_user@example.com") -> User:
    user = User(email=email, full_name="Voice Synth Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_synthesize_requires_authentication(async_client: AsyncClient):
    payload = {"text": "Hello world"}
    res = await async_client.post("/api/v1/voice/synthesize", json=payload)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_synthesize_valid_text_returns_audio_wav(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_valid@example.com")
    set_auth_cookie(async_client, user)

    mock_tts = MockTTSProvider()
    set_tts_provider_for_testing(mock_tts)

    try:
        payload = {"text": "You have two meetings scheduled today."}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("audio/wav")
        assert len(res.content) > 44
        assert res.content.startswith(b"RIFF")
    finally:
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_synthesize_rejects_empty_text(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_empty@example.com")
    set_auth_cookie(async_client, user)

    payload = {"text": ""}
    res = await async_client.post("/api/v1/voice/synthesize", json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_rejects_oversized_text(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_oversized@example.com")
    set_auth_cookie(async_client, user)

    payload = {"text": "A" * 1001}
    res = await async_client.post("/api/v1/voice/synthesize", json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_voice_and_language_parameters(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_params@example.com")
    set_auth_cookie(async_client, user)

    mock_tts = MockTTSProvider()
    set_tts_provider_for_testing(mock_tts)

    try:
        payload = {
            "text": "Weather forecast is clear today.",
            "voice": "mock-voice-1",
            "language": "en-US",
        }
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 200
        assert len(res.content) > 44
    finally:
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_synthesize_timeout_handling(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_timeout@example.com")
    set_auth_cookie(async_client, user)

    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("timeout")
    set_tts_provider_for_testing(mock_tts)

    try:
        payload = {"text": "This request will time out."}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 504
    finally:
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_synthesize_rate_limit_handling(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_ratelimit@example.com")
    set_auth_cookie(async_client, user)

    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("rate_limit")
    set_tts_provider_for_testing(mock_tts)

    try:
        payload = {"text": "This request exceeds rate limit."}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 429
    finally:
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_synthesize_upstream_provider_failure(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "synth_upstream_fail@example.com")
    set_auth_cookie(async_client, user)

    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("generic")
    set_tts_provider_for_testing(mock_tts)

    try:
        payload = {"text": "This request encounters upstream failure."}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 502
    finally:
        set_tts_provider_for_testing(None)
