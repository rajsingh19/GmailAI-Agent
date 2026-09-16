"""
Voice API endpoints for speech-to-text, text-to-speech, conversational voice turns, and cancellation.
"""
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.metrics import metrics_registry
from app.db.session import get_db
from app.models.user import User
from app.ai.schemas.agent import AgentChatMessage
from app.voice.audio_validator import (
    AudioDurationError,
    AudioFormatError,
    AudioSizeError,
    AudioValidationError,
)
from app.voice.execution_manager import (
    CrossUserCancellationError,
    ExecutionNotFoundError,
    VoiceExecutionManager,
)
from app.voice.providers.base import (
    VoiceAuthenticationError,
    VoiceInvalidAudioError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)
from app.voice.schemas import (
    SynthesizeRequest,
    TranscribeResponse,
    VoiceCancelResponse,
    VoiceChatResponse,
)
from app.voice.service import VoiceCancelledError, VoiceService

logger = logging.getLogger(settings.PROJECT_NAME)

router = APIRouter()


def _ensure_voice_enabled() -> None:
    """Guards endpoints behind VOICE_ENABLED feature toggle."""
    if not settings.VOICE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice interaction feature is disabled",
        )


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """
    Transcribes uploaded audio into normalized verbatim text.
    Enforces payload size, container anti-spoofing, and decodability validation.
    """
    _ensure_voice_enabled()

    content_type = file.content_type or "audio/wav"
    audio_bytes = await file.read()

    try:
        result = await VoiceService.transcribe_audio(
            audio_bytes=audio_bytes,
            declared_content_type=content_type,
            language=language,
        )
        metrics_registry.inc_counter("voice_requests_total", labels={"operation": "transcribe", "status": "success"})
        return TranscribeResponse(
            transcript=result.transcript,
            detected_language=result.detected_language,
            confidence=result.confidence,
            duration_seconds=result.duration_seconds,
        )
    except AudioSizeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=exc.message)
    except AudioFormatError as exc:
        if exc.code == "UNSUPPORTED_MEDIA_TYPE":
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=exc.message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except AudioDurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except VoiceTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc))
    except VoiceRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except VoiceAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except VoiceProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/synthesize")
async def synthesize_speech(
    request: SynthesizeRequest,
    current_user: User = Depends(get_current_user),
) -> Response:
    """
    Synthesizes input text into speech audio bytes.
    Enforces maximum character bounds and returns binary audio stream.
    """
    _ensure_voice_enabled()

    try:
        result = await VoiceService.synthesize_speech(
            text=request.text,
            voice=request.voice,
            language=request.language,
        )
        headers = {}
        if result.duration_seconds is not None:
            headers["X-Audio-Duration-Seconds"] = str(result.duration_seconds)

        metrics_registry.inc_counter("voice_requests_total", labels={"operation": "synthesize", "status": "success"})
        return Response(
            content=result.audio_bytes,
            media_type=result.content_type,
            headers=headers,
        )
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except VoiceTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc))
    except VoiceRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except VoiceAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except VoiceProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/chat", response_model=VoiceChatResponse)
async def voice_chat(
    file: UploadFile = File(...),
    history: Optional[str] = Form(None),
    confirmation_token: Optional[str] = Form(None),
    synthesize_speech: bool = Form(True),
    language: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Primary conversational voice turn endpoint:
    Audio -> STT -> Existing AgentOrchestrator -> TTS.
    Returns transcript, assistant message, optional audio, and confirmation challenges.
    """
    _ensure_voice_enabled()

    content_type = file.content_type or "audio/wav"
    audio_bytes = await file.read()

    # Parse optional conversation history
    parsed_history: Optional[List[AgentChatMessage]] = None
    if history:
        try:
            raw_list = json.loads(history)
            if isinstance(raw_list, list):
                parsed_history = [AgentChatMessage(**item) for item in raw_list]
        except Exception as exc:
            logger.warning("Failed to parse voice chat history payload: %s", exc)

    try:
        response = await VoiceService.process_voice_chat(
            user=current_user,
            db=db,
            audio_bytes=audio_bytes,
            content_type=content_type,
            history=parsed_history,
            confirmation_token=confirmation_token,
            synthesize_speech=synthesize_speech,
            language=language,
        )
        metrics_registry.inc_counter("voice_requests_total", labels={"operation": "chat", "status": "success"})
        return response

    except AudioSizeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=exc.message)
    except AudioFormatError as exc:
        if exc.code == "UNSUPPORTED_MEDIA_TYPE":
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=exc.message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except AudioDurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except VoiceCancelledError as exc:
        raise HTTPException(status_code=499, detail="Client closed request or execution cancelled")
    except VoiceTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc))
    except VoiceRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except VoiceAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except VoiceProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/cancel/{execution_id}", response_model=VoiceCancelResponse)
async def cancel_voice_execution(
    execution_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Cancels an active voice execution safely across workers.
    Enforces user-scoped IDOR protection.
    """
    _ensure_voice_enabled()

    try:
        await VoiceExecutionManager.cancel_execution(
            execution_id=execution_id,
            requesting_user_id=current_user.id,
        )
        metrics_registry.inc_counter("voice_cancellations_total", labels={"status": "cancelled"})
        return VoiceCancelResponse(status="cancelled", execution_id=execution_id)
    except (CrossUserCancellationError, ExecutionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found",
        )
