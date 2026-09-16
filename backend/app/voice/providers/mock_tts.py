"""
Deterministic Mock Text-to-Speech Provider for hermetic testing and offline development.
"""
import asyncio
import struct
from typing import List, Optional

from app.voice.providers.base import (
    SpeechSynthesisResult,
    TextToSpeechProvider,
    VoiceAuthenticationError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)


def _generate_valid_wav_bytes(duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generates valid 16-bit mono PCM RIFF WAV audio bytes."""
    num_samples = int(sample_rate * duration_seconds)
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample
    riff_size = 36 + data_size

    header = bytearray()
    header.extend(b"RIFF")
    header.extend(struct.pack("<I", riff_size))
    header.extend(b"WAVE")
    header.extend(b"fmt ")
    header.extend(struct.pack("<I", 16))          # Subchunk1Size (16 for PCM)
    header.extend(struct.pack("<H", 1))           # AudioFormat (1 = PCM)
    header.extend(struct.pack("<H", 1))           # NumChannels (1 = mono)
    header.extend(struct.pack("<I", sample_rate)) # SampleRate
    header.extend(struct.pack("<I", sample_rate * 2)) # ByteRate
    header.extend(struct.pack("<H", 2))           # BlockAlign (2 bytes)
    header.extend(struct.pack("<H", 16))          # BitsPerSample
    header.extend(b"data")
    header.extend(struct.pack("<I", data_size))

    # Silence (0x0000 per sample)
    samples = b"\x00\x00" * num_samples
    return bytes(header) + samples


class MockTTSProvider(TextToSpeechProvider):
    """
    Mock TTS provider that returns valid WAV audio bytes without cloud API calls.
    Supports failure simulation for testing graceful degradation.
    """

    def __init__(self):
        self.simulated_error: Optional[str] = None
        self.simulated_delay: float = 0.0

    def set_simulated_error(self, error_type: Optional[str]) -> None:
        """Simulates provider failure: ('auth', 'rate_limit', 'timeout', 'generic')"""
        self.simulated_error = error_type

    def set_simulated_delay(self, delay_seconds: float) -> None:
        self.simulated_delay = delay_seconds

    def get_supported_voices(self) -> List[str]:
        return ["mock-voice-1", "mock-voice-2", "en-US-Standard-C"]

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        timeout: float = 15.0,
    ) -> SpeechSynthesisResult:
        if self.simulated_delay > 0:
            if self.simulated_delay > timeout:
                await asyncio.sleep(timeout)
                raise VoiceTimeoutError("Mock TTS synthesis timed out")
            await asyncio.sleep(self.simulated_delay)

        if self.simulated_error == "auth":
            raise VoiceAuthenticationError("Mock TTS credentials rejected")
        elif self.simulated_error == "rate_limit":
            raise VoiceRateLimitError("Mock TTS rate limit exceeded")
        elif self.simulated_error == "timeout":
            raise VoiceTimeoutError("Mock TTS synthesis timed out")
        elif self.simulated_error == "generic":
            raise VoiceProviderError("Mock TTS provider error")

        wav_bytes = _generate_valid_wav_bytes(duration_seconds=1.0)
        return SpeechSynthesisResult(
            audio_bytes=wav_bytes,
            content_type="audio/wav",
            duration_seconds=1.0,
        )
