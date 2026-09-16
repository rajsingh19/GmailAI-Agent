"""
Deterministic Mock Speech-to-Text Provider for hermetic testing and offline development.
"""
import asyncio
from typing import List, Optional

from app.voice.providers.base import (
    SpeechToTextProvider,
    TranscriptionResult,
    VoiceAuthenticationError,
    VoiceInvalidAudioError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)


class MockSTTProvider(SpeechToTextProvider):
    """
    Mock STT provider that returns predictable transcripts without external API calls.
    Supports failure simulation for robust edge-case testing.
    """

    def __init__(self, default_transcript: str = "What tasks do I have scheduled today?"):
        self.default_transcript = default_transcript
        self.simulated_error: Optional[str] = None
        self.simulated_delay: float = 0.0

    def set_mock_transcript(self, transcript: str) -> None:
        """Sets the transcript to return on subsequent transcribe calls."""
        self.default_transcript = transcript

    def set_simulated_error(self, error_type: Optional[str]) -> None:
        """
        Simulates provider failure:
        error_type in ('auth', 'rate_limit', 'timeout', 'invalid_audio', 'generic')
        """
        self.simulated_error = error_type

    def set_simulated_delay(self, delay_seconds: float) -> None:
        """Simulates latency before returning response."""
        self.simulated_delay = delay_seconds

    def get_supported_formats(self) -> List[str]:
        return [
            "audio/wav",
            "audio/webm",
            "audio/ogg",
            "audio/mp3",
            "audio/mpeg",
            "audio/m4a",
            "audio/x-m4a",
        ]

    async def transcribe(
        self,
        audio_bytes: bytes,
        content_type: str,
        language: Optional[str] = None,
        timeout: float = 15.0,
    ) -> TranscriptionResult:
        if self.simulated_delay > 0:
            if self.simulated_delay > timeout:
                await asyncio.sleep(timeout)
                raise VoiceTimeoutError("Mock STT transcription timed out")
            await asyncio.sleep(self.simulated_delay)

        if self.simulated_error == "auth":
            raise VoiceAuthenticationError("Mock STT credentials rejected")
        elif self.simulated_error == "rate_limit":
            raise VoiceRateLimitError("Mock STT rate limit exceeded")
        elif self.simulated_error == "timeout":
            raise VoiceTimeoutError("Mock STT transcription timed out")
        elif self.simulated_error == "invalid_audio":
            raise VoiceInvalidAudioError("Mock STT cannot decode audio")
        elif self.simulated_error == "generic":
            raise VoiceProviderError("Mock STT internal server error")

        return TranscriptionResult(
            transcript=self.default_transcript,
            detected_language=language or "en",
            confidence=0.98,
            duration_seconds=round(len(audio_bytes) / 16000.0, 2),
        )
