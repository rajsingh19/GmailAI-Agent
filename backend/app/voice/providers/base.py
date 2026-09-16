"""
Provider-neutral abstract interfaces and data transfer objects for Speech-to-Text and Text-to-Speech.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class VoiceProviderError(Exception):
    """Base exception for voice provider operations."""
    pass


class VoiceAuthenticationError(VoiceProviderError):
    """Raised when voice provider authentication/credentials fail."""
    pass


class VoiceRateLimitError(VoiceProviderError):
    """Raised when voice provider quota or rate limit is reached."""
    pass


class VoiceTimeoutError(VoiceProviderError):
    """Raised when voice provider request times out."""
    pass


class VoiceInvalidAudioError(VoiceProviderError):
    """Raised when audio cannot be parsed or decoded by the provider."""
    pass


@dataclass
class TranscriptionResult:
    """Structured transcription result returned by SpeechToTextProvider."""
    transcript: str
    detected_language: Optional[str] = None
    confidence: Optional[float] = None
    duration_seconds: Optional[float] = None


@dataclass
class SpeechSynthesisResult:
    """Structured speech synthesis result returned by TextToSpeechProvider."""
    audio_bytes: bytes
    content_type: str
    duration_seconds: Optional[float] = None


class SpeechToTextProvider(ABC):
    """
    Provider-neutral interface for speech recognition.
    Supports general multimodal audio understanding as well as dedicated transcription APIs.
    """

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        content_type: str,
        language: Optional[str] = None,
        timeout: float = 15.0,
    ) -> TranscriptionResult:
        """Transcribes raw audio bytes into normalized text."""
        pass

    @abstractmethod
    def get_supported_formats(self) -> List[str]:
        """Returns list of supported MIME types (e.g. audio/webm, audio/wav)."""
        pass


class TextToSpeechProvider(ABC):
    """
    Provider-neutral interface for speech synthesis.
    """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        timeout: float = 15.0,
    ) -> SpeechSynthesisResult:
        """Synthesizes text into audio bytes."""
        pass

    @abstractmethod
    def get_supported_voices(self) -> List[str]:
        """Returns available voice identifiers."""
        pass
