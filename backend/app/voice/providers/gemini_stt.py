"""
Google Gemini Speech-to-Text Provider.
Transcribes audio recordings via Google Generative Language REST API using configurable GEMINI_STT_MODEL.
"""
import base64
import logging
from typing import List, Optional
import httpx

from app.core.config import settings
from app.voice.providers.base import (
    SpeechToTextProvider,
    TranscriptionResult,
    VoiceAuthenticationError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)

logger = logging.getLogger(settings.PROJECT_NAME)


class GeminiSTTProvider(SpeechToTextProvider):
    """
    Speech-to-Text Provider leveraging Google Gemini REST API.
    Sends raw audio inline using inlineData with audio MIME type and verbatim transcription prompt.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_STT_MODEL

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
        """
        Calls Gemini API with audio payload and returns transcribed text.
        """
        if not self.api_key:
            raise VoiceAuthenticationError("Gemini API key is not configured for Speech-to-Text.")

        url = f"{self.BASE_URL}/models/{self.model_name}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        base64_audio = base64.b64encode(audio_bytes).decode("utf-8")

        prompt_text = (
            "Transcribe the following audio recording verbatim. "
            "Output only the exact transcribed speech text without commentary, conversational preamble, formatting, or notes."
        )
        if language:
            prompt_text += f" The primary spoken language is expected to be {language}."

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt_text},
                        {
                            "inlineData": {
                                "mimeType": content_type,
                                "data": base64_audio,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code in (401, 403) or (resp.status_code == 400 and "API_KEY_INVALID" in resp.text):
                logger.warning("Gemini STT authentication failure (status %d)", resp.status_code)
                raise VoiceAuthenticationError(f"Gemini API authentication failed: {resp.status_code}")
            elif resp.status_code == 429:
                logger.warning("Gemini STT rate limit exceeded.")
                raise VoiceRateLimitError("Gemini STT rate limit exceeded.")
            elif resp.status_code >= 400:
                logger.error("Gemini STT API error (status %d)", resp.status_code)
                raise VoiceProviderError(f"Gemini STT provider returned HTTP {resp.status_code}")

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return TranscriptionResult(transcript="", detected_language=language, confidence=0.0)

            parts = candidates[0].get("content", {}).get("parts", [])
            transcript = "".join(p.get("text", "") for p in parts).strip()

            return TranscriptionResult(
                transcript=transcript,
                detected_language=language,
                confidence=0.95 if transcript else 0.0,
            )

        except httpx.TimeoutException as exc:
            logger.warning("Gemini STT request timed out after %.1f seconds: %s", timeout, exc)
            raise VoiceTimeoutError("Gemini STT transcription request timed out.") from exc
        except (VoiceAuthenticationError, VoiceRateLimitError, VoiceTimeoutError, VoiceProviderError):
            raise
        except Exception as exc:
            logger.exception("Unexpected error in Gemini STT provider: %s", exc)
            raise VoiceProviderError(f"Unexpected error in Gemini STT: {exc}") from exc
