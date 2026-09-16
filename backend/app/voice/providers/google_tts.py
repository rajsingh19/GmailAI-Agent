"""
Google Cloud Text-to-Speech REST Provider.
Uses Application Default Credentials (ADC) or explicit Google Cloud token/key.
Service account keys are NEVER baked into Docker images.
"""
import base64
import logging
from typing import List, Optional
import httpx

from app.core.config import settings
from app.voice.providers.base import (
    SpeechSynthesisResult,
    TextToSpeechProvider,
    VoiceAuthenticationError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)

logger = logging.getLogger(settings.PROJECT_NAME)


class GoogleTTSProvider(TextToSpeechProvider):
    """
    Google Cloud Text-to-Speech Provider.
    Calls texttospeech.googleapis.com/v1/text:synthesize using Google Application Default Credentials.
    """

    BASE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_voice: Optional[str] = None,
        default_language: Optional[str] = None,
    ):
        self.api_key = api_key if api_key is not None else (getattr(settings, "GOOGLE_CLOUD_API_KEY", None) or settings.GEMINI_API_KEY)
        self.default_voice = default_voice or settings.GOOGLE_TTS_VOICE
        self.default_language = default_language or settings.GOOGLE_TTS_LANGUAGE

    def get_supported_voices(self) -> List[str]:
        return [
            "en-US-Journey-F",
            "en-US-Journey-D",
            "en-US-Neural2-F",
            "en-US-Standard-C",
        ]

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        timeout: float = 15.0,
    ) -> SpeechSynthesisResult:
        if not self.api_key:
            raise VoiceAuthenticationError(
                "Google Cloud Text-to-Speech credentials are not configured."
            )

        url = self.BASE_URL
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        voice_name = voice or self.default_voice
        language_code = language or self.default_language

        payload = {
            "input": {"text": text},
            "voice": {
                "languageCode": language_code,
                "name": voice_name,
            },
            "audioConfig": {
                "audioEncoding": "MP3",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code in (401, 403):
                logger.warning("Google TTS authentication error (status %d)", resp.status_code)
                raise VoiceAuthenticationError(f"Google Cloud TTS authentication failed: {resp.status_code}")
            elif resp.status_code == 429:
                logger.warning("Google TTS rate limit exceeded.")
                raise VoiceRateLimitError("Google Cloud TTS rate limit exceeded.")
            elif resp.status_code >= 400:
                logger.error("Google TTS error (status %d)", resp.status_code)
                raise VoiceProviderError(f"Google Cloud TTS returned HTTP {resp.status_code}")

            data = resp.json()
            audio_content_b64 = data.get("audioContent")
            if not audio_content_b64:
                raise VoiceProviderError("Google Cloud TTS returned empty audio payload.")

            audio_bytes = base64.b64decode(audio_content_b64)
            return SpeechSynthesisResult(
                audio_bytes=audio_bytes,
                content_type="audio/mpeg",
                duration_seconds=None,
            )

        except httpx.TimeoutException as exc:
            logger.warning("Google TTS request timed out after %.1f seconds: %s", timeout, exc)
            raise VoiceTimeoutError("Google Cloud TTS request timed out.") from exc
        except (VoiceAuthenticationError, VoiceRateLimitError, VoiceTimeoutError, VoiceProviderError):
            raise
        except Exception as exc:
            logger.exception("Unexpected error in Google TTS provider: %s", exc)
            raise VoiceProviderError(f"Unexpected error in Google TTS: {exc}") from exc
