"""
Factory for instantiating configurable Speech-to-Text and Text-to-Speech providers.
"""
from typing import Optional
import logging

from app.core.config import settings
from app.voice.providers.base import (
    SpeechToTextProvider,
    TextToSpeechProvider,
    VoiceProviderError,
)
from app.voice.providers.gemini_stt import GeminiSTTProvider
from app.voice.providers.google_tts import GoogleTTSProvider
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import MockTTSProvider

logger = logging.getLogger(settings.PROJECT_NAME)

# Test override hooks
_TEST_STT_PROVIDER: Optional[SpeechToTextProvider] = None
_TEST_TTS_PROVIDER: Optional[TextToSpeechProvider] = None


def set_stt_provider_for_testing(provider: Optional[SpeechToTextProvider]) -> None:
    """Sets a mock or custom STT provider for automated testing."""
    global _TEST_STT_PROVIDER
    _TEST_STT_PROVIDER = provider


def set_tts_provider_for_testing(provider: Optional[TextToSpeechProvider]) -> None:
    """Sets a mock or custom TTS provider for automated testing."""
    global _TEST_TTS_PROVIDER
    _TEST_TTS_PROVIDER = provider


def get_stt_provider(provider_name: Optional[str] = None) -> SpeechToTextProvider:
    """
    Returns an instance of the configured Speech-to-Text provider.
    """
    if _TEST_STT_PROVIDER is not None:
        return _TEST_STT_PROVIDER

    name = (provider_name or settings.STT_PROVIDER).lower()

    if name == "gemini":
        return GeminiSTTProvider(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEMINI_STT_MODEL,
        )
    elif name == "mock":
        return MockSTTProvider()
    else:
        logger.warning("Unrecognized STT provider '%s', falling back to MockSTTProvider", name)
        return MockSTTProvider()


def get_tts_provider(provider_name: Optional[str] = None) -> TextToSpeechProvider:
    """
    Returns an instance of the configured Text-to-Speech provider.
    """
    if _TEST_TTS_PROVIDER is not None:
        return _TEST_TTS_PROVIDER

    name = (provider_name or settings.TTS_PROVIDER).lower()

    if name == "google":
        return GoogleTTSProvider(
            default_voice=settings.GOOGLE_TTS_VOICE,
            default_language=settings.GOOGLE_TTS_LANGUAGE,
        )
    elif name == "mock":
        return MockTTSProvider()
    else:
        logger.warning("Unrecognized TTS provider '%s', falling back to MockTTSProvider", name)
        return MockTTSProvider()
