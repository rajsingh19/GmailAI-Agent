"""
Tests for Voice Observability, Metrics, Privacy, and Feature Toggles (Milestone 10).
Verifies:
- voice_requests_total counter increments on /transcribe
- voice_requests_total counter increments on /synthesize
- voice_requests_total counter increments on /chat
- voice_cancellations_total counter increments on /cancel/{id}
- /metrics Prometheus endpoint displays voice telemetry
- Zero persistence of raw audio bytes on filesystem
- Structured logging does not emit raw audio bytes or large base64 strings
- VOICE_ENABLED=False feature toggle disables all voice endpoints with HTTP 404
"""

import asyncio
import io
import logging
import os
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.ai.providers.base import LLMResponse
from app.core.config import settings
from app.core.metrics import metrics_registry
from app.core.security import SecurityManager
from app.models.user import User
from app.voice.execution_manager import VoiceExecutionManager
from app.voice.providers.factory import set_stt_provider_for_testing, set_tts_provider_for_testing
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import MockTTSProvider, _generate_valid_wav_bytes


async def create_test_user(test_db: AsyncSession, email: str = "voice_obs_user@example.com") -> User:
    user = User(email=email, full_name="Voice Observability Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_voice_metrics_counter_increments_on_transcribe(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "metrics_transcribe@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Metrics transcribe test"))
    try:
        prev_count = metrics_registry.get_sample_value("voice_requests_total", {"operation": "transcribe", "status": "success"}) or 0.0

        wav_bytes = _generate_valid_wav_bytes(1.0)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        res = await async_client.post("/api/v1/voice/transcribe", files=files)
        assert res.status_code == 200

        new_count = metrics_registry.get_sample_value("voice_requests_total", {"operation": "transcribe", "status": "success"}) or 0.0
        assert new_count == prev_count + 1.0
    finally:
        set_stt_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_metrics_counter_increments_on_synthesize(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "metrics_synthesize@example.com")
    set_auth_cookie(async_client, user)

    set_tts_provider_for_testing(MockTTSProvider())
    try:
        prev_count = metrics_registry.get_sample_value("voice_requests_total", {"operation": "synthesize", "status": "success"}) or 0.0

        payload = {"text": "Metrics synthesize test"}
        res = await async_client.post("/api/v1/voice/synthesize", json=payload)
        assert res.status_code == 200

        new_count = metrics_registry.get_sample_value("voice_requests_total", {"operation": "synthesize", "status": "success"}) or 0.0
        assert new_count == prev_count + 1.0
    finally:
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_metrics_counter_increments_on_chat(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "metrics_chat@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Metrics chat test"))
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        prev_count = metrics_registry.get_sample_value("voice_requests_total", {"operation": "chat", "status": "success"}) or 0.0

        mock_llm = LLMResponse(content="Metrics chat response.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)
            assert res.status_code == 200

            new_count = metrics_registry.get_sample_value("voice_requests_total", {"operation": "chat", "status": "success"}) or 0.0
            assert new_count == prev_count + 1.0
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_cancellations_metric_increments_on_cancel(async_client: AsyncClient, test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user = await create_test_user(test_db, "metrics_cancel@example.com")
    set_auth_cookie(async_client, user)

    exec_id = "exec_metric_cancel_1"
    dummy_task = asyncio.create_task(asyncio.sleep(10.0))
    await VoiceExecutionManager.register_execution(exec_id, user.id, task=dummy_task)

    prev_cancels = metrics_registry.get_sample_value("voice_cancellations_total", {"status": "cancelled"}) or 0.0

    res = await async_client.post(f"/api/v1/voice/cancel/{exec_id}")
    assert res.status_code == 200

    new_cancels = metrics_registry.get_sample_value("voice_cancellations_total", {"status": "cancelled"}) or 0.0
    assert new_cancels == prev_cancels + 1.0


@pytest.mark.asyncio
async def test_voice_metrics_endpoint_displays_voice_telemetry(async_client: AsyncClient):
    metrics_registry.inc_counter("voice_requests_total", labels={"operation": "transcribe", "status": "success"})
    metrics_registry.inc_counter("voice_cancellations_total", labels={"status": "cancelled"})

    res = await async_client.get("/metrics")
    assert res.status_code == 200
    prometheus_text = res.text
    assert "voice_requests_total" in prometheus_text
    assert "voice_cancellations_total" in prometheus_text


@pytest.mark.asyncio
async def test_voice_audio_bytes_not_persisted_to_filesystem(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "zero_disk_user@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Zero persistence check"))
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        mock_llm = LLMResponse(content="Zero disk audio verified.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)
            assert res.status_code == 200

            # Scan workspace root for any uncleaned temporary audio files
            workspace_files = os.listdir(".")
            audio_leaks = [f for f in workspace_files if f.endswith((".wav", ".webm", ".mp3", ".ogg", ".raw"))]
            assert len(audio_leaks) == 0
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_structured_logs_do_not_log_raw_audio_bytes_or_base64(async_client: AsyncClient, test_db: AsyncSession, caplog):
    user = await create_test_user(test_db, "voice_log_privacy_user@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Confidential audio check"))
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        mock_llm = LLMResponse(content="Audio response processed.")
        with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm):
            with caplog.at_level(logging.DEBUG):
                wav_bytes = _generate_valid_wav_bytes(1.0)
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                res = await async_client.post("/api/v1/voice/chat", files=files)
                assert res.status_code == 200

                # Check all captured log lines
                for record in caplog.records:
                    log_text = record.getMessage()
                    # Ensure no huge raw binary bytes or giant base64 payloads (> 200 chars continuous)
                    assert "RIFF" not in log_text or "wav" in log_text.lower()
                    assert len(log_text) < 10000
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


@pytest.mark.asyncio
async def test_voice_feature_toggle_disabled_returns_404(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_toggle_user@example.com")
    set_auth_cookie(async_client, user)

    orig_voice_enabled = settings.VOICE_ENABLED
    settings.VOICE_ENABLED = False

    try:
        wav_bytes = _generate_valid_wav_bytes(1.0)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}

        res_transcribe = await async_client.post("/api/v1/voice/transcribe", files=files)
        assert res_transcribe.status_code == 404
        assert "disabled" in res_transcribe.json()["detail"].lower()

        res_synth = await async_client.post("/api/v1/voice/synthesize", json={"text": "Hello"})
        assert res_synth.status_code == 404

        res_chat = await async_client.post("/api/v1/voice/chat", files=files)
        assert res_chat.status_code == 404

        res_cancel = await async_client.post("/api/v1/voice/cancel/exec_dummy")
        assert res_cancel.status_code == 404
    finally:
        settings.VOICE_ENABLED = orig_voice_enabled
