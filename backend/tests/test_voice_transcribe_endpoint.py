"""
Tests for Voice Transcription Endpoint (POST /api/v1/voice/transcribe).
Verifies:
- 401 Unauthorized for unauthenticated requests
- 200 OK with transcript, confidence, language, and duration on valid audio
- 422 Unprocessable Entity when audio file is missing
- 400 Bad Request on empty or zero-byte audio payload
- 400 Bad Request on container signature spoofing
- 413 Payload Too Large on oversized audio payload
- Language hint parameter propagation
- 502 Bad Gateway when upstream STT provider fails
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.voice.providers.base import VoiceProviderError
from app.voice.providers.factory import set_stt_provider_for_testing
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import _generate_valid_wav_bytes


async def create_test_user(test_db: AsyncSession, email: str = "voice_transcribe_user@example.com") -> User:
    user = User(email=email, full_name="Voice Transcribe Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_transcribe_requires_authentication(async_client: AsyncClient):
    wav_bytes = _generate_valid_wav_bytes(1.0)
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    res = await async_client.post("/api/v1/voice/transcribe", files=files)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_transcribe_valid_wav_audio_success(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_success@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="List my priority tasks for this week")
    set_stt_provider_for_testing(mock_stt)

    try:
        wav_bytes = _generate_valid_wav_bytes(1.0)
        files = {"file": ("test.wav", wav_bytes, "audio/wav")}
        res = await async_client.post("/api/v1/voice/transcribe", files=files)
        assert res.status_code == 200
        data = res.json()
        assert data["transcript"] == "List my priority tasks for this week"
        assert data["confidence"] == 0.98
        assert data["detected_language"] == "en"
        assert data["duration_seconds"] is not None
    finally:
        set_stt_provider_for_testing(None)


@pytest.mark.asyncio
async def test_transcribe_rejects_missing_audio_file(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_missing_file@example.com")
    set_auth_cookie(async_client, user)

    res = await async_client.post("/api/v1/voice/transcribe", data={})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_file(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_empty_file@example.com")
    set_auth_cookie(async_client, user)

    files = {"file": ("empty.wav", b"", "audio/wav")}
    res = await async_client.post("/api/v1/voice/transcribe", files=files)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_rejects_spoofed_mime_type(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_spoof@example.com")
    set_auth_cookie(async_client, user)

    # Send invalid/corrupted bytes declared as audio/wav
    files = {"file": ("spoof.wav", b"FAKE_AUDIO_DATA_PAYLOAD_NOT_WAV", "audio/wav")}
    res = await async_client.post("/api/v1/voice/transcribe", files=files)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_rejects_oversized_payload(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_oversized@example.com")
    set_auth_cookie(async_client, user)

    wav_bytes = _generate_valid_wav_bytes(1.0)
    with patch("app.core.config.settings.MAX_AUDIO_BYTES", 50):
        files = {"file": ("large.wav", wav_bytes, "audio/wav")}
        res = await async_client.post("/api/v1/voice/transcribe", files=files)
        assert res.status_code == 413


@pytest.mark.asyncio
async def test_transcribe_propagates_language_hint(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_lang@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Bonjour le monde")
    set_stt_provider_for_testing(mock_stt)

    try:
        wav_bytes = _generate_valid_wav_bytes(1.0)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"language": "fr"}
        res = await async_client.post("/api/v1/voice/transcribe", files=files, data=data)
        assert res.status_code == 200
        assert res.json()["detected_language"] == "fr"
    finally:
        set_stt_provider_for_testing(None)


@pytest.mark.asyncio
async def test_transcribe_handles_upstream_provider_failure(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "transcribe_fail@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider()
    mock_stt.set_simulated_error("generic")
    set_stt_provider_for_testing(mock_stt)

    try:
        wav_bytes = _generate_valid_wav_bytes(1.0)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        res = await async_client.post("/api/v1/voice/transcribe", files=files)
        assert res.status_code == 502
    finally:
        set_stt_provider_for_testing(None)
