"""
Voice Service Coordinator.
Orchestrates audio validation, Speech-to-Text, the existing AgentOrchestrator,
and Text-to-Speech with multi-worker cancellation checkpoints and TTS degradation.
"""
import asyncio
import base64
import logging
import time
import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.ai.agent.orchestrator import AgentOrchestrator
from app.ai.schemas.agent import AgentChatMessage
from app.voice.audio_validator import (
    AudioValidationError,
    validate_audio_payload,
)
from app.voice.execution_manager import VoiceExecutionManager
from app.voice.providers.base import (
    SpeechSynthesisResult,
    TranscriptionResult,
    VoiceProviderError,
)
from app.voice.providers.factory import get_stt_provider, get_tts_provider
from app.voice.schemas import VoiceChatResponse

logger = logging.getLogger(settings.PROJECT_NAME)


class VoiceCancelledError(Exception):
    """Raised when an active voice execution is cancelled by user request."""
    pass


class VoiceService:
    """
    Coordinates end-to-end conversational voice processing without duplicating agent logic.
    """

    @classmethod
    async def transcribe_audio(
        cls,
        audio_bytes: bytes,
        declared_content_type: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Validates audio container and executes Speech-to-Text transcription.
        """
        canonical_mime = validate_audio_payload(audio_bytes, declared_content_type)
        provider = get_stt_provider()
        return await provider.transcribe(
            audio_bytes=audio_bytes,
            content_type=canonical_mime,
            language=language,
            timeout=float(settings.VOICE_REQUEST_TIMEOUT) / 2.0,
        )

    @classmethod
    async def synthesize_speech(
        cls,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> SpeechSynthesisResult:
        """
        Validates text bounds and generates speech audio via Text-to-Speech provider.
        """
        clean_text = text.strip()
        if not clean_text:
            raise AudioValidationError("Text for synthesis cannot be empty.", code="INVALID_TEXT")

        if len(clean_text) > settings.MAX_TTS_CHARS:
            raise AudioValidationError(
                f"Text length ({len(clean_text)}) exceeds maximum allowed limit of {settings.MAX_TTS_CHARS} characters.",
                code="TEXT_TOO_LONG",
            )

        provider = get_tts_provider()
        return await provider.synthesize(
            text=clean_text,
            voice=voice,
            language=language,
            timeout=float(settings.VOICE_REQUEST_TIMEOUT) / 2.0,
        )

    @classmethod
    async def process_voice_chat(
        cls,
        user: User,
        db: AsyncSession,
        audio_bytes: bytes,
        content_type: str,
        history: Optional[List[AgentChatMessage]] = None,
        confirmation_token: Optional[str] = None,
        synthesize_speech: bool = True,
        language: Optional[str] = None,
    ) -> VoiceChatResponse:
        """
        Executes a full voice turn:
        1. Validates audio container & size.
        2. Transcribes speech -> text via STT.
        3. Passes text to existing AgentOrchestrator for multi-tool reasoning & execution.
        4. Synthesizes assistant response -> audio via TTS (with graceful degradation).
        5. Coordinates checkpoints with VoiceExecutionManager for cancellation.
        """
        execution_id = f"v_exec_{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()

        await VoiceExecutionManager.register_execution(execution_id, user.id)

        try:
            # Checkpoint 0: pre-flight cancellation check
            if await VoiceExecutionManager.is_cancel_requested(execution_id):
                raise VoiceCancelledError("Voice execution cancelled by user")

            # 1. Container & Signature Validation
            canonical_mime = validate_audio_payload(audio_bytes, content_type)

            # Checkpoint 1: post-validation cancellation check
            if await VoiceExecutionManager.is_cancel_requested(execution_id):
                raise VoiceCancelledError("Voice execution cancelled by user")

            # 2. Speech-to-Text Transcription
            t_stt_start = time.perf_counter()
            stt_provider = get_stt_provider()
            transcription = await stt_provider.transcribe(
                audio_bytes=audio_bytes,
                content_type=canonical_mime,
                language=language,
                timeout=float(settings.VOICE_REQUEST_TIMEOUT) / 2.0,
            )
            stt_duration_ms = round((time.perf_counter() - t_stt_start) * 1000, 2)

            transcript = transcription.transcript.strip()
            if not transcript:
                return VoiceChatResponse(
                    execution_id=execution_id,
                    transcript="",
                    message="I could not hear or understand any speech. Please try speaking again clearly.",
                    tts_status="disabled",
                    metadata={"stt_duration_ms": stt_duration_ms, "duration_ms": stt_duration_ms},
                )

            # Checkpoint 2: post-STT cancellation check
            if await VoiceExecutionManager.is_cancel_requested(execution_id):
                raise VoiceCancelledError("Voice execution cancelled by user")

            # 3. Existing AgentOrchestrator Turn
            t_agent_start = time.perf_counter()
            orchestrator = AgentOrchestrator()
            agent_response = await orchestrator.process_message(
                user=user,
                db=db,
                message=transcript,
                history=history,
                confirmation_token=confirmation_token,
            )
            agent_duration_ms = round((time.perf_counter() - t_agent_start) * 1000, 2)

            # Checkpoint 3: post-Agent cancellation check
            if await VoiceExecutionManager.is_cancel_requested(execution_id):
                raise VoiceCancelledError("Voice execution cancelled by user")

            # 4. Text-to-Speech Synthesis with Graceful Degradation
            audio_b64: Optional[str] = None
            audio_mime: Optional[str] = None
            tts_status = "disabled"
            tts_error: Optional[str] = None
            tts_duration_ms = 0.0

            if synthesize_speech and agent_response.message:
                t_tts_start = time.perf_counter()
                tts_provider = get_tts_provider()
                # Bound synthesis text to prevent excessive provider payload
                tts_text = agent_response.message[:settings.MAX_TTS_CHARS].strip()

                try:
                    tts_result = await tts_provider.synthesize(
                        text=tts_text,
                        language=language or settings.GOOGLE_TTS_LANGUAGE,
                        timeout=float(settings.VOICE_REQUEST_TIMEOUT) / 2.0,
                    )
                    audio_b64 = base64.b64encode(tts_result.audio_bytes).decode("utf-8")
                    audio_mime = tts_result.content_type
                    tts_status = "success"
                except Exception as exc:
                    # CRITICAL REQUIREMENT: Graceful degradation
                    # If TTS fails, NEVER discard the agent's successful response!
                    logger.warning(
                        "[%s] TTS synthesis failed; degrading gracefully to text-only: %s",
                        execution_id,
                        exc,
                    )
                    tts_status = "degraded"
                    tts_error = "Speech synthesis temporarily unavailable"
                finally:
                    tts_duration_ms = round((time.perf_counter() - t_tts_start) * 1000, 2)

            total_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return VoiceChatResponse(
                execution_id=execution_id,
                transcript=transcript,
                message=agent_response.message,
                audio_base64=audio_b64,
                audio_content_type=audio_mime,
                tts_status=tts_status,
                tts_error=tts_error,
                tool_activities=agent_response.tool_activities,
                confirmation_required=agent_response.confirmation_required,
                metadata={
                    "stt_duration_ms": stt_duration_ms,
                    "agent_duration_ms": agent_duration_ms,
                    "tts_duration_ms": tts_duration_ms,
                    "total_duration_ms": total_duration_ms,
                    "model": agent_response.metadata.get("model", settings.effective_model_name),
                    "stt_model": getattr(stt_provider, "model_name", "unknown"),
                },
            )

        finally:
            await VoiceExecutionManager.complete_execution(execution_id)
