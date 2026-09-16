"""
Tests for Voice Providers (Milestone 10).
Verifies:
- MockSTTProvider deterministic transcription, error simulation, and delay
- MockTTSProvider valid PCM WAV byte generation and error simulation
- GeminiSTTProvider payload formatting, auth guard, rate limit, and timeout handling
- GoogleTTSProvider error handling and format compatibility
"""

import asyncio
import io
import wave
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.core.config import settings
from app.voice.providers.base import (
    VoiceAuthenticationError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import MockTTSProvider
from app.voice.providers.gemini_stt import GeminiSTTProvider
from app.voice.providers.google_tts import GoogleTTSProvider


@pytest.mark.asyncio
async def test_mock_stt_returns_configured_transcription():
    provider = MockSTTProvider(default_transcript="What is on my schedule today?")
    result = await provider.transcribe(b"dummy-audio-bytes", "audio/wav")
    assert result.transcript == "What is on my schedule today?"
    assert result.confidence == 0.98
    assert "audio/wav" in provider.get_supported_formats()


@pytest.mark.asyncio
async def test_mock_stt_error_simulation():
    provider = MockSTTProvider()
    provider.set_simulated_error("generic")
    with pytest.raises(Exception, match="Mock STT internal server error"):
        await provider.transcribe(b"dummy-audio", "audio/webm")


@pytest.mark.asyncio
async def test_mock_stt_delay_simulation():
    provider = MockSTTProvider(default_transcript="Hello delayed")
    provider.set_simulated_delay(0.05)
    start_time = asyncio.get_event_loop().time()
    res = await provider.transcribe(b"audio", "audio/ogg")
    duration = asyncio.get_event_loop().time() - start_time
    assert duration >= 0.04
    assert res.transcript == "Hello delayed"


@pytest.mark.asyncio
async def test_mock_tts_generates_valid_wav_audio():
    provider = MockTTSProvider()
    result = await provider.synthesize("You have 3 tasks due tomorrow.")
    assert result.content_type == "audio/wav"
    assert len(result.audio_bytes) > 44
    assert result.audio_bytes.startswith(b"RIFF")

    # Verify standard readable WAV header with 16kHz mono PCM
    with wave.open(io.BytesIO(result.audio_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() > 0


@pytest.mark.asyncio
async def test_mock_tts_error_simulation():
    provider = MockTTSProvider()
    provider.set_simulated_error("generic")
    with pytest.raises(VoiceProviderError, match="Mock TTS provider error"):
        await provider.synthesize("Hello world")


@pytest.mark.asyncio
async def test_gemini_stt_missing_api_key_raises_auth_error():
    provider = GeminiSTTProvider(api_key="")
    with pytest.raises(VoiceAuthenticationError, match="Gemini API key is not configured"):
        await provider.transcribe(b"audio-bytes", "audio/wav")


@pytest.mark.asyncio
async def test_gemini_stt_transcribes_with_mocked_gemini_api():
    provider = GeminiSTTProvider(api_key="valid-test-gemini-key", model_name="gemini-3.5-transcribe")

    mock_resp_json = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Summarize my unread emails from yesterday."}]
                }
            }
        ]
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_resp_json

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await provider.transcribe(b"RIFFfakeWAVE", "audio/wav", language="en")

        assert result.transcript == "Summarize my unread emails from yesterday."
        assert result.detected_language == "en"
        assert result.confidence == 0.95
        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        assert "gemini-3.5-transcribe" in call_url


@pytest.mark.asyncio
async def test_gemini_stt_rate_limit_error_handling():
    provider = GeminiSTTProvider(api_key="test-key", model_name="gemini-3.5-transcribe")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.text = "Resource exhausted: Rate limit exceeded"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(VoiceRateLimitError, match="rate limit exceeded"):
            await provider.transcribe(b"dummy", "audio/wav")


@pytest.mark.asyncio
async def test_gemini_stt_timeout_error_handling():
    provider = GeminiSTTProvider(api_key="test-key", model_name="gemini-3.5-transcribe")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        with pytest.raises(VoiceTimeoutError, match="timed out"):
            await provider.transcribe(b"dummy", "audio/wav", timeout=1.0)


@pytest.mark.asyncio
async def test_google_tts_missing_credentials_raises_error():
    provider = GoogleTTSProvider(api_key="")
    with pytest.raises(VoiceAuthenticationError, match="credentials are not configured"):
        await provider.synthesize("Test speech message")
