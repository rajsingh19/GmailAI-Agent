"""
Pydantic schemas for voice endpoints (transcribe, synthesize, voice chat, cancellation).
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.ai.schemas.agent import ToolActivityInfo, ConfirmationChallenge


class TranscribeResponse(BaseModel):
    transcript: str = Field(..., description="Normalized verbatim text transcribed from audio")
    detected_language: Optional[str] = Field(None, description="ISO language code detected by provider")
    confidence: Optional[float] = Field(None, description="Transcription confidence score (0.0 to 1.0)")
    duration_seconds: Optional[float] = Field(None, description="Estimated audio recording duration in seconds")


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000, description="Text string to synthesize into speech")
    voice: Optional[str] = Field(None, description="Optional voice model identifier")
    language: Optional[str] = Field(None, description="Optional language tag (e.g. en-US)")


class VoiceChatResponse(BaseModel):
    execution_id: str = Field(..., description="Unique correlation ID for this conversational voice turn")
    transcript: str = Field(..., description="Transcribed user speech query")
    message: str = Field(..., description="Assistant synthesized text response from AgentOrchestrator")
    audio_base64: Optional[str] = Field(None, description="Base64-encoded synthesized speech audio bytes if enabled")
    audio_content_type: Optional[str] = Field(None, description="MIME type of synthesized audio (e.g. audio/wav, audio/mpeg)")
    tts_status: str = Field("success", description="Status of speech synthesis: 'success', 'degraded', or 'disabled'")
    tts_error: Optional[str] = Field(None, description="Sanitized reason if TTS degraded to text-only")
    tool_activities: List[ToolActivityInfo] = Field(default_factory=list, description="List of tool actions performed")
    confirmation_required: Optional[ConfirmationChallenge] = Field(None, description="M6 cryptographic confirmation challenge if high-risk tool invoked")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metrics and metadata")


class VoiceCancelResponse(BaseModel):
    status: str = Field("cancelled", description="Cancellation outcome")
    execution_id: str = Field(..., description="ID of the cancelled voice execution")
