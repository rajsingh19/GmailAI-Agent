# Milestone 10 Implementation Plan v2: Voice + Multimodal AI Interaction

**Version**: 2.0 (Revised)  
**Status**: Pending Review  
**Milestones 1–9**: Complete & Frozen (456/456 tests passing)

---

## 1. Executive Summary & Architectural Integrity

Milestone 10 introduces an enterprise-grade voice interaction layer to the Personal AI Assistant.

> [!IMPORTANT]
> **Cardinal Invariant: Voice Must NOT Create a Second AI Architecture.**
> Voice is strictly an audio input/output modal adapter. It accepts user speech, validates and decodes the container, transcribes it to text via a provider-neutral `SpeechToTextProvider`, feeds the text into the **existing** `AgentOrchestrator`, uses the **existing** `ToolRegistry` and `ToolExecutor` (Gmail, Calendar, Tasks, Reminders, Knowledge RAG), and optionally speaks the assistant's response via an abstract `TextToSpeechProvider`.
>
> All existing M1–M9 security, user isolation, cryptographic confirmation, distributed rate limiting, and observability guarantees remain strictly frozen and preserved.

```
                        VOICE INPUT (Microphone)
                                  │ (Audio Bytes: WebM / WAV / Ogg / MP3)
                                  ▼
                ┌───────────────────────────────────┐
                │ Audio Container & Signature Check │
                │  - MIME type vs magic bytes       │
                │  - Decodability & length check    │
                │  - Configurable size & duration   │
                └─────────────────┬─────────────────┘
                                  │
                                  ▼
                ┌───────────────────────────────────┐
                │     SpeechToTextProvider          │
                │  (Gemini REST / Mock / Cloud STT) │
                └─────────────────┬─────────────────┘
                                  │ (Verbatim Normalized Transcript Text)
                                  ▼
                ┌───────────────────────────────────┐
                │     Existing AgentOrchestrator    │
                └─────────────────┬─────────────────┘
                                  │
                                  ▼
                ┌───────────────────────────────────┐
                │   Existing ToolRegistry & Executor│
                │  - Gmail / Calendar / Tasks / RAG │
                │  - M6 ConfirmationService Guard   │
                └─────────────────┬─────────────────┘
                                  │ (Synthesized Assistant Text)
                                  ▼
                ┌───────────────────────────────────┐
                │     TextToSpeechProvider          │
                │  (Google Cloud TTS / Mock TTS)    │
                │  - Graceful degradation on error  │
                └─────────────────┬─────────────────┘
                                  │ (Audio Bytes: WAV / MP3 or None on degraded)
                                  ▼
                        VOICE OUTPUT (Speaker)
```

---

## 2. Voice Provider Abstraction & Model Configuration

The voice layer decouples speech recognition and speech synthesis through clean provider interfaces. The backend owns provider credentials; provider-specific APIs and keys are never exposed to the frontend.

### 2.1 Provider-Neutral Interfaces (`backend/app/voice/providers/base.py`)
```python
@dataclass
class TranscriptionResult:
    transcript: str
    detected_language: Optional[str] = None
    confidence: Optional[float] = None
    duration_seconds: Optional[float] = None


@dataclass
class SpeechSynthesisResult:
    audio_bytes: bytes
    content_type: str
    duration_seconds: Optional[float] = None


class SpeechToTextProvider(ABC):
    """
    Provider-neutral interface for speech recognition.
    Supports general multimodal LLM audio understanding as well as dedicated transcription APIs.
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
        """Returns list of supported MIME types (e.g. audio/webm, audio/wav, audio/mp3)."""
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
```

### 2.2 Concrete Implementations & Configurable Models

1. **`GeminiSTTProvider`** (`backend/app/voice/providers/gemini_stt.py`):
   - Configurable Model: `GEMINI_STT_MODEL` (default: `gemini-3.5-transcribe`, configurable via environment variables).
   - Uses Google Generative Language REST API (`v1beta/models/{GEMINI_STT_MODEL}:generateContent`).
   - Sends audio inline using `inlineData` with audio MIME type and a strict verbatim transcription prompt (*"Transcribe the following audio recording verbatim. Output only the exact transcribed speech text without commentary, formatting, or notes."*).
   - Reuses existing `GEMINI_API_KEY`.
2. **`MockSTTProvider`** (`backend/app/voice/providers/mock_stt.py`):
   - Fast, deterministic in-memory provider for unit, integration, and security test suites.
3. **`GoogleTTSProvider`** (`backend/app/voice/providers/google_tts.py`):
   - Uses Google Cloud Text-to-Speech REST API (`v1/text:synthesize`).
   - Production-safe authentication: Uses Google Application Default Credentials (ADC) or explicit Google Cloud service account environment variables. **No service account keys are baked into Docker images.**
4. **`MockTTSProvider`** (`backend/app/voice/providers/mock_tts.py`):
   - Returns valid RIFF WAV PCM audio bytes for testing and local zero-cost verification.

### 2.3 Provider Configuration Factory (`backend/app/voice/providers/factory.py`)
- Selected via settings:
  - `STT_PROVIDER`: `"gemini"` or `"mock"`
  - `GEMINI_STT_MODEL`: `"gemini-3.5-transcribe"` (configurable via environment variables)
  - `TTS_PROVIDER`: `"google"` or `"mock"`

---

## 3. Audio Validation & Container Anti-Spoofing

Voice endpoints do not trust client `Content-Type` headers alone. Audio payloads undergo strict container validation:

| Verification | Rule | Violation Code |
| :--- | :--- | :--- |
| **Declared MIME Type** | Must be in supported list (`audio/webm`, `audio/wav`, `audio/ogg`, `audio/mp3`, `audio/mpeg`, `audio/m4a`, `audio/x-m4a`) | HTTP 415 Unsupported Media Type |
| **Container Magic Bytes** | Actual header must match signature:<br>- WAV: `RIFF....WAVE`<br>- WebM: `\x1a\x45\xdf\xa3` (EBML header)<br>- Ogg: `OggS`<br>- MP3: `ID3` or sync frame `\xff\xfb` / `\xff\xf3` | HTTP 400 Bad Request (`INVALID_AUDIO_CONTAINER`) |
| **Container Decodability** | Minimum header length verified (e.g. WAV $\ge$ 44 bytes with valid chunk sizes; WebM valid EBML element structure). Truncated or renamed text files fail immediately. | HTTP 400 Bad Request (`MALFORMED_AUDIO`) |
| **Payload Size** | Bounded by configurable `MAX_AUDIO_BYTES` (default: `10485760` / 10MB) | HTTP 413 Payload Too Large |
| **Duration Limit** | Bounded by configurable `MAX_AUDIO_DURATION_SECONDS` (default: `60`) | HTTP 400 Bad Request (`AUDIO_TOO_LONG`) |
| **Authentication** | Valid session cookie required | HTTP 401 Unauthorized |

---

## 4. Multi-Worker Distributed Cancellation Model

The process-local `asyncio.Task` registry is augmented with shared Redis execution state to guarantee safe cancellation across multi-worker Uvicorn processes and multi-pod deployments:

### 4.1 Shared Execution State in Redis
When an execution begins, the worker creates a Redis key:
```
Key: voice:exec:{execution_id}
TTL: 120 seconds
Value (JSON):
{
  "execution_id": "exec_8f4d92a1",
  "user_id": "usr_abc123",
  "worker_id": "host-pod-1:pid-4521:uuid",
  "created_at": "2026-09-16T16:00:00Z",
  "status": "running",
  "cancel_requested": false
}
```

### 4.2 Cancellation Flow (`POST /api/v1/voice/cancel/{execution_id}`)
1. **User Ownership Verification**:
   - The handler reads `voice:exec:{execution_id}` from Redis.
   - If the key does not exist or `record.user_id != current_user.id`, returns HTTP 404 (`EXECUTION_NOT_FOUND`).
   - **IDOR Protection**: User A can never cancel or inspect User B's execution.
2. **Atomic Flag Update**:
   - Updates Redis key with `cancel_requested: true` and `status: "cancelled"`.
3. **Local Task Cancellation**:
   - If `record.worker_id == current_worker_id`, the worker directly executes `task.cancel()` on the in-flight `asyncio.Task`.
   - In a multi-worker setup, the executing worker checks the cancellation token at pipeline checkpoints:
     - Checkpoint 1: Immediately after STT transcription.
     - Checkpoint 2: Prior to calling `AgentOrchestrator.process_message`.
     - Checkpoint 3: Prior to calling TTS synthesis.
4. **Database Safety**:
   - Cancellation aborts in-flight AI calls and TTS synthesis. It does **not** corrupt already committed database transactions.

---

## 5. M6 Confirmation Safety Preservation

> [!CAUTION]
> **Voice Must NOT Bypass M6 Confirmation Challenges.**
> Dangerous operations (e.g. deleting tasks, cancelling reminders) require explicit HMAC-SHA256 tokens issued by `ConfirmationService`.

### Reusing M6 ConfirmationManager
1. User speaks: *"Delete my task called Project Proposal"*.
2. STT converts to transcript: *"Delete my task called Project Proposal"*.
3. Existing `AgentOrchestrator` invokes `ToolExecutor.execute_tool("delete_task", {"task_id": "task_123"})`.
4. `delete_task` detects a high-risk action without a valid confirmation token $\rightarrow$ invokes existing `ConfirmationService.issue_challenge(...)`.
5. The assistant returns a `ConfirmationChallenge` with cryptographic token `<payload_b64>.<sig_b64>`.
6. Both text and audio response state: *"Are you sure you want to delete task 'Project Proposal'?"*
7. **Verbal Affirmed Rejection**: Simple spoken affirmations (e.g. *"yes"*, *"confirm"*, *"do it"*) without the server-issued cryptographic token are strictly rejected.
8. To execute the deletion, the follow-up request must provide the `confirmation_token` generated by `ConfirmationService`.
9. Client-supplied `confirmed=true` has zero authority.

---

## 6. TTS Failure Graceful Degradation

If speech transcription and agent reasoning succeed, but text-to-speech synthesis fails (e.g. due to provider timeout, quota, or network failure):

- **The assistant text response MUST NOT be discarded.**
- The response returns HTTP 200 with:
  - `message`: Full synthesized text response from the agent.
  - `audio_base64`: `null`
  - `audio_content_type`: `null`
  - `tts_status`: `"degraded"`
  - `tts_error`: `"Speech synthesis temporarily unavailable"`
  - `tool_activities`: Full tool execution list.
  - `confirmation_required`: Any pending challenge.
- A structured warning is logged: `logger.warning("[%s] TTS synthesis failed; degrading gracefully to text-only: %s", execution_id, exc)`.

---

## 7. Audio Privacy & Storage Policy

- **Zero Audio Persistence by Default**: `VOICE_AUDIO_PERSISTENCE = False`.
- Audio bytes are streamed in-memory, validated, transcribed, and immediately garbage-collected.
- Audio is **never** written to local disk, temporary files, or database tables.
- Sensitive transcripts and raw audio are excluded from structured logs. Logs capture only low-cardinality metadata: `execution_id`, `request_id`, `duration_ms`, `audio_bytes`, `provider`, and status code.

---

## 8. Configurable Limits & Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `VOICE_ENABLED` | `true` | Master toggle for voice endpoints |
| `STT_PROVIDER` | `"gemini"` | Speech-to-text provider (`"gemini"`, `"mock"`) |
| `GEMINI_STT_MODEL` | `"gemini-3.5-transcribe"` | Configurable Gemini model for audio transcription |
| `TTS_PROVIDER` | `"mock"` | Text-to-speech provider (`"google"`, `"mock"`) |
| `GOOGLE_TTS_VOICE` | `"en-US-Journey-F"` | Configurable voice identifier |
| `GOOGLE_TTS_LANGUAGE` | `"en-US"` | Language tag for TTS |
| `MAX_AUDIO_BYTES` | `10485760` (10 MB) | Maximum audio payload size in bytes |
| `MAX_AUDIO_DURATION_SECONDS` | `60` | Maximum recording length in seconds |
| `MAX_TRANSCRIPT_CHARS` | `2000` | Maximum transcription character length |
| `MAX_TTS_CHARS` | `1000` | Maximum text length accepted for TTS |
| `VOICE_REQUEST_TIMEOUT` | `30` | Overall voice turn timeout in seconds |
| `RATE_LIMIT_VOICE_LIMIT` | `20` | Max voice requests per window |
| `RATE_LIMIT_VOICE_WINDOW` | `60` | Voice rate-limiting window in seconds |
| `VOICE_AUDIO_PERSISTENCE` | `false` | Permanent audio storage flag (strictly false) |

---

## 9. API Specification

Mounted under `/api/v1/voice/*`. All endpoints require authentication (`Depends(get_current_user)`).

### 9.1 `POST /api/v1/voice/transcribe`
- **Request**: Multipart Form: `file` (audio upload), optional `language` (str).
- **Response**:
  ```json
  {
    "transcript": "What tasks are due today?",
    "duration_seconds": 2.8,
    "language": "en"
  }
  ```

### 9.2 `POST /api/v1/voice/synthesize`
- **Request**: JSON Body:
  ```json
  {
    "text": "You have two tasks due today: submit report, review PR.",
    "voice": "en-US-Journey-F",
    "language": "en-US"
  }
  ```
- **Response**: Binary audio bytes (`Content-Type: audio/wav` or `audio/mpeg`) with header `X-Audio-Duration-Seconds`.

### 9.3 `POST /api/v1/voice/chat`
- **Request**: Multipart Form:
  - `file`: Audio file.
  - `history`: Optional JSON string of prior messages.
  - `confirmation_token`: Optional cryptographic token for confirming high-risk actions.
  - `synthesize_speech`: Optional boolean (default: `true`).
- **Response**:
  ```json
  {
    "execution_id": "exec_8f4d92a1",
    "transcript": "Delete my task called Buy milk",
    "message": "Are you sure you want to delete the task 'Buy milk'?",
    "audio_base64": "UklGRi...",
    "audio_content_type": "audio/wav",
    "tts_status": "success",
    "tool_activities": [
      {
        "name": "Delete Task",
        "status": "pending_confirmation",
        "summary": "Deletion requires confirmation"
      }
    ],
    "confirmation_required": {
      "token": "eyJhbGciOi...",
      "tool_name": "delete_task",
      "action": "delete",
      "target_id": "task_123",
      "message": "Are you sure you want to delete this task?",
      "expires_at": "2026-09-16T16:15:00Z"
    },
    "metadata": {
      "model": "gemini-2.0-flash",
      "duration_ms": 1420.5
    }
  }
  ```

### 9.4 `POST /api/v1/voice/cancel/{execution_id}`
- **Response**:
  ```json
  {
    "status": "cancelled",
    "execution_id": "exec_8f4d92a1"
  }
  ```

---

## 10. Frontend Voice UI Design

Extends `frontend/src/components/AgentChat.tsx` with `VoiceControls.tsx`:

- **Microphone Button** `[ 🎤 Speak ]`: Toggles audio recording using browser MediaRecorder API (capturing `audio/webm;codecs=opus` or `audio/wav`).
- **Pulsing Visual Indicator**: Displays recording state, duration timer (`00:04 / 01:00`), [Stop], and [Cancel] buttons.
- **Audio Playback**: Auto-plays assistant audio with an animated soundwave badge and an [Interrupt / Stop Audio] button.
- **Degraded TTS Handling**: If `tts_status == "degraded"`, displays assistant text seamlessly with a small badge: *"Audio unavailable — text response shown"*.
- **Confirmation Prompts**: Renders existing M6 challenge buttons (`[ Confirm ]` / `[ Cancel ]`) for voice-initiated high-risk actions.

---

## 11. Testing Strategy ($\ge 85$ New Tests)

Target: **456 baseline + $\ge 85$ new M10 tests = $\ge 541$ total passing tests**.

| Test Suite | File | Tests Planned | Scope Covered |
| :--- | :--- | :--- | :--- |
| **1. Voice Providers** | `tests/test_voice_providers.py` | 10 | STT & TTS interface compliance, `GeminiSTTProvider` payload formatting, `MockSTTProvider`, `MockTTSProvider`, factory fallback, invalid provider configuration. |
| **2. Audio Validation & Anti-Spoofing** | `tests/test_voice_audio_validation.py` | 12 | MIME type verification, magic byte checks (WAV, WebM, Ogg, MP3), container decodability, truncated headers, text file spoofing rejection, oversized file rejection (>10MB), duration limit rejection. |
| **3. Transcribe Endpoint** | `tests/test_voice_transcribe_endpoint.py` | 8 | `/api/v1/voice/transcribe` valid flow, unauthenticated 401, timeout handling (504), provider failure (502), empty file rejection. |
| **4. Synthesize Endpoint** | `tests/test_voice_synthesize_endpoint.py` | 8 | `/api/v1/voice/synthesize` valid flow, character limit (>1000 chars rejected), empty text, unauthenticated 401, timeout handling. |
| **5. Voice Chat Pipeline** | `tests/test_voice_chat_pipeline.py` | 12 | Full voice turn through `AgentOrchestrator`, history preservation, tool activity propagation, voice query for Tasks/Calendar/Gmail, RAG personal knowledge search via voice. |
| **6. TTS Failure Graceful Degradation** | `tests/test_voice_tts_degradation.py` | 6 | STT succeeds + Agent succeeds + TTS raises timeout/error $\rightarrow$ returns 200 with assistant text, `audio_base64=None`, `tts_status="degraded"`. |
| **7. M6 Confirmation Safety** | `tests/test_voice_confirmation_safety.py` | 10 | Voice command for high-risk tool returns `ConfirmationChallenge`, unbound verbal affirmation without token fails, valid token succeeds, replayed token rejected, expired token rejected, cross-user token rejected. |
| **8. Multi-Worker Cancellation & IDOR** | `tests/test_voice_cancellation_and_idor.py` | 10 | Shared Redis cancellation state, cross-user cancellation blocked (HTTP 404), local `asyncio.Task` abort, non-existent execution, database transaction integrity after cancel. |
| **9. Rate Limiting & Quotas** | `tests/test_voice_rate_limiting_and_quotas.py` | 6 | Voice rate limit (20 req/min), `X-RateLimit-*` headers, Retry-After on 429, fail-open vs fail-closed policy. |
| **10. Observability & Privacy** | `tests/test_voice_observability_and_privacy.py` | 8 | Low-cardinality Prometheus metrics, log redaction (zero raw audio or tokens logged), X-Request-ID propagation. |
| **11. M1–M9 Regression Sanity** | `tests/test_m1_m9_regression_preservation.py` | 5 | Verifies M1-M8 OAuth/Gmail/Calendar/Tasks/Reminders and M9 security headers, advisory lock 84920184, and rate limiting remain 100% functional. |

**Total Planned New Tests: 95 tests ($\ge 85$ required).**

---

## 12. Backward Compatibility & Rollback

- **Zero Schema Migrations**: Voice processing is stateless; no database tables or migrations are added.
- **Zero Impact on Existing Chat**: `POST /api/v1/agent/chat` and existing text workflows remain 100% untouched.
- **Feature Flag / Instant Rollback**: Setting `VOICE_ENABLED=false` disables all voice endpoints (HTTP 404). Rollback requires only a git revert with zero database downtime.
