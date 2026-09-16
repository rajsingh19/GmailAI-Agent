"""
Tests for Graceful TTS Degradation (Milestone 10).
Verifies:
- When STT and Agent succeed, but TTS encounters provider failure, the API returns HTTP 200
- tts_status is set to "degraded" and audio_base64 is None
- Sanitized error explanation provided in tts_error
- Degradation behavior across TTS timeout, rate limit, authentication, and generic provider errors
- Entire assistant message and tool activities preserved intact
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.ai.providers.base import LLMResponse
from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.voice.providers.factory import set_stt_provider_for_testing, set_tts_provider_for_testing
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import MockTTSProvider, _generate_valid_wav_bytes


async def create_test_user(test_db: AsyncSession, email: str = "tts_degrade_user@example.com") -> User:
    user = User(email=email, full_name="TTS Degrade Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_tts_degradation_returns_200_when_tts_fails_generic(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "tts_fail_generic@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Summarize recent updates")
    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("generic")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    try:
        mock_llm = LLMResponse(content="Here are your latest updates without audio.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["message"] == "Here are your latest updates without audio."
            assert data["tts_status"] == "degraded"
            assert data["audio_base64"] is None
            assert data["tts_error"] == "Speech synthesis temporarily unavailable"
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_tts_degradation_when_tts_times_out(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "tts_fail_timeout@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Check notifications")
    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("timeout")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    try:
        mock_llm = LLMResponse(content="You have 2 new notifications.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["message"] == "You have 2 new notifications."
            assert data["tts_status"] == "degraded"
            assert data["audio_base64"] is None
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_tts_degradation_when_tts_rate_limited(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "tts_fail_ratelimit@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Review agenda")
    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("rate_limit")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    try:
        mock_llm = LLMResponse(content="Your agenda is clear.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["message"] == "Your agenda is clear."
            assert data["tts_status"] == "degraded"
            assert data["audio_base64"] is None
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_tts_degradation_when_tts_auth_fails(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "tts_fail_auth@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Status report")
    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("auth")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    try:
        mock_llm = LLMResponse(content="All services operational.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["message"] == "All services operational."
            assert data["tts_status"] == "degraded"
            assert data["audio_base64"] is None
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_tts_degraded_preserves_full_assistant_message(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "tts_preserve_message@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Detailed summary")
    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("generic")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    long_message = "This is a multi-sentence detailed explanation. " * 5

    try:
        mock_llm = LLMResponse(content=long_message)
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["message"] == long_message
            assert data["tts_status"] == "degraded"
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_tts_degraded_preserves_tool_activity_and_confirmation(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "tts_preserve_tools@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Check pending items")
    mock_tts = MockTTSProvider()
    mock_tts.set_simulated_error("generic")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    try:
        with patch("app.ai.agent.orchestrator.AgentOrchestrator.process_message") as mock_orchestrator:
            from unittest.mock import AsyncMock
            mock_orchestrator_async = AsyncMock()
            from app.ai.schemas.agent import AgentChatResponse, ConfirmationChallenge, ToolActivityInfo

            mock_challenge = ConfirmationChallenge(
                tool="delete_task",
                confirmation_token="hmac-token-xyz123",
                action="delete",
                target_id="task-42",
                message="Are you sure you want to delete task-42?",
            )
            mock_tool_act = ToolActivityInfo(
                name="Delete Task",
                status="confirmation_required",
                summary="Awaiting confirmation to delete task-42",
            )
            mock_orchestrator_async.return_value = AgentChatResponse(
                execution_id="exec-degraded-confirm",
                message="Deleting task-42 requires your authorization.",
                tool_activities=[mock_tool_act],
                confirmation_required=mock_challenge,
            )

            with patch("app.ai.agent.orchestrator.AgentOrchestrator.process_message", mock_orchestrator_async):
                wav_bytes = _generate_valid_wav_bytes(1.0)
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                res = await async_client.post("/api/v1/voice/chat", files=files)

                assert res.status_code == 200
                data = res.json()
                assert data["tts_status"] == "degraded"
                assert data["confirmation_required"] is not None
                assert data["confirmation_required"]["action"] == "delete"
                assert data["confirmation_required"]["confirmation_token"] == "hmac-token-xyz123"
                assert len(data["tool_activities"]) == 1
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)
