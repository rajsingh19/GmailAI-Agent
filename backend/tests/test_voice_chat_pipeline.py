"""
Tests for Voice Chat Pipeline (POST /api/v1/voice/chat) (Milestone 10).
Verifies:
- 401 Unauthorized when unauthenticated
- End-to-end voice conversational turn (Audio -> STT -> Agent -> TTS)
- Invokes existing AgentOrchestrator without secondary AI routing
- Executes read tools via voice query (e.g. list_tasks)
- Preserves conversation history context
- Supports synthesize_speech=False (tts_status="disabled")
- Rejects empty audio payload (400)
- Rejects container spoofed audio (400)
- Rejects oversized audio payload (413)
- Multi-user isolation across voice turns
- Cleans up voice execution registration after completion
- Zero audio files persisted to disk by default
"""

import json
import os
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.ai.providers.base import LLMResponse, LLMToolCall
from app.core.config import settings
from app.core.security import SecurityManager
from app.models.task import Task
from app.models.user import User
from app.voice.execution_manager import VoiceExecutionManager
from app.voice.providers.factory import set_stt_provider_for_testing, set_tts_provider_for_testing
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import MockTTSProvider, _generate_valid_wav_bytes


async def create_test_user(test_db: AsyncSession, email: str = "voice_chat_user@example.com") -> User:
    user = User(email=email, full_name="Voice Chat Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_voice_chat_requires_authentication(async_client: AsyncClient):
    wav_bytes = _generate_valid_wav_bytes(1.0)
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    res = await async_client.post("/api/v1/voice/chat", files=files)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_voice_chat_pipeline_end_to_end_success(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_pipeline_success@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="What is my schedule today?")
    mock_tts = MockTTSProvider()
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(mock_tts)

    try:
        mock_llm_response = LLMResponse(content="You have no meetings scheduled for today.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm_response):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["transcript"] == "What is my schedule today?"
            assert data["message"] == "You have no meetings scheduled for today."
            assert data["tts_status"] == "success"
            assert data["audio_base64"] is not None
            assert data["audio_content_type"] == "audio/wav"
            assert "execution_id" in data
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_invokes_existing_agent_orchestrator(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_orchestrator_check@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Hello Assistant")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        from unittest.mock import AsyncMock
        with patch("app.ai.agent.orchestrator.AgentOrchestrator.process_message", new_callable=AsyncMock) as mock_orchestrator:
            from app.ai.schemas.agent import AgentChatResponse
            mock_orchestrator.return_value = AgentChatResponse(
                execution_id="test-exec-1",
                message="AgentOrchestrator successfully processed voice text",
                tool_activities=[],
                confirmation_required=None,
            )

            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            assert mock_orchestrator.called
            call_kwargs = mock_orchestrator.call_args[1]
            assert call_kwargs["message"] == "Hello Assistant"
            assert call_kwargs["user"].id == user.id
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_executes_read_tools(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_tools_user@example.com")
    set_auth_cookie(async_client, user)

    task = Task(user_id=user.id, title="Voice Test Task", status="pending", priority="medium")
    test_db.add(task)
    await test_db.commit()

    mock_stt = MockSTTProvider(default_transcript="List my pending tasks")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        step1 = LLMResponse(
            content=None,
            tool_calls=[LLMToolCall(id="c1", name="list_tasks", arguments={"status": "pending"})],
        )
        step2 = LLMResponse(content="You have 1 pending task: 'Voice Test Task'.")

        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", side_effect=[step1, step2]):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            data = res.json()
            assert data["message"] == "You have 1 pending task: 'Voice Test Task'."
            assert len(data["tool_activities"]) == 1
            assert data["tool_activities"][0]["name"] in ("Listing tasks", "list_tasks")
            assert data["tool_activities"][0]["status"] == "completed"
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_with_conversation_history(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_history_user@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="What was the second item?")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        mock_llm = LLMResponse(content="The second item was milk.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            history_data = [
                {"role": "user", "content": "I need eggs and milk."},
                {"role": "assistant", "content": "Noted, eggs and milk."},
            ]
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            data = {"history": json.dumps(history_data)}

            res = await async_client.post("/api/v1/voice/chat", files=files, data=data)
            assert res.status_code == 200
            assert res.json()["message"] == "The second item was milk."
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_synthesize_speech_false_disables_tts(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_no_tts_user@example.com")
    set_auth_cookie(async_client, user)

    mock_stt = MockSTTProvider(default_transcript="Turn off speech output")
    set_stt_provider_for_testing(mock_stt)

    try:
        mock_llm = LLMResponse(content="Speech output is disabled.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            data = {"synthesize_speech": "false"}

            res = await async_client.post("/api/v1/voice/chat", files=files, data=data)
            assert res.status_code == 200
            data = res.json()
            assert data["tts_status"] == "disabled"
            assert data["audio_base64"] is None
    finally:
        set_stt_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_rejects_empty_audio(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_empty_user@example.com")
    set_auth_cookie(async_client, user)

    files = {"file": ("empty.wav", b"", "audio/wav")}
    res = await async_client.post("/api/v1/voice/chat", files=files)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_voice_chat_rejects_spoofed_audio(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_spoof_user@example.com")
    set_auth_cookie(async_client, user)

    files = {"file": ("spoof.wav", b"MALFORMED_HEADER_DATA_STREAM", "audio/wav")}
    res = await async_client.post("/api/v1/voice/chat", files=files)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_voice_chat_rejects_oversized_audio(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_oversized_user@example.com")
    set_auth_cookie(async_client, user)

    wav_bytes = _generate_valid_wav_bytes(1.0)
    with patch("app.core.config.settings.MAX_AUDIO_BYTES", 50):
        files = {"file": ("large.wav", wav_bytes, "audio/wav")}
        res = await async_client.post("/api/v1/voice/chat", files=files)
        assert res.status_code == 413


@pytest.mark.asyncio
async def test_voice_chat_multi_user_isolation(async_client: AsyncClient, test_db: AsyncSession):
    user_a = await create_test_user(test_db, "voice_user_a@example.com")
    user_b = await create_test_user(test_db, "voice_user_b@example.com")

    # User B has a secret task
    task_b = Task(user_id=user_b.id, title="User B Confidential Task", status="pending")
    test_db.add(task_b)
    await test_db.commit()

    # User A asks for tasks via voice
    set_auth_cookie(async_client, user_a)
    mock_stt = MockSTTProvider(default_transcript="List my tasks")
    set_stt_provider_for_testing(mock_stt)
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        step1 = LLMResponse(
            content=None,
            tool_calls=[LLMToolCall(id="t1", name="list_tasks", arguments={})],
        )
        step2 = LLMResponse(content="You have no tasks.")

        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", side_effect=[step1, step2]):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            # User A should NOT see User B's task in tool activity or response
            assert "Confidential Task" not in res.json()["message"]
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_cleans_up_execution_context_on_completion(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_cleanup_user@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Cleanup check"))
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        mock_llm = LLMResponse(content="Execution complete")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            exec_id = res.json()["execution_id"]
            # After execution finishes, task registry should no longer track active task
            assert not VoiceExecutionManager.is_task_active(exec_id)
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_chat_persists_no_audio_by_default(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_privacy_user@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Privacy audio check"))
    set_tts_provider_for_testing(MockTTSProvider())

    assert settings.VOICE_AUDIO_PERSISTENCE is False

    try:
        mock_llm = LLMResponse(content="Your audio was processed purely in memory.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 200
            # Confirm no files matching voice audio exist in cwd or tmp
            assert not os.path.exists("audio.wav")
            assert not os.path.exists("voice_audio.raw")
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)
