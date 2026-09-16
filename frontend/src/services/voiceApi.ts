import { API_BASE_URL } from './api';
import { AgentChatMessage, ConfirmationChallenge, ToolActivityInfo } from './api';

export interface TranscribeResponse {
  transcript: string;
  detected_language?: string | null;
  confidence?: number | null;
  duration_seconds?: number | null;
}

export interface SynthesizeRequest {
  text: string;
  voice?: string | null;
  language?: string | null;
}

export interface VoiceChatResponse {
  execution_id: string;
  transcript: string;
  message: string;
  audio_base64?: string | null;
  audio_content_type?: string | null;
  tts_status: 'success' | 'degraded' | 'disabled';
  tts_error?: string | null;
  tool_activities: ToolActivityInfo[];
  confirmation_required?: ConfirmationChallenge | null;
  metadata: Record<string, any>;
}

export interface VoiceCancelResponse {
  status: string;
  execution_id: string;
}

/**
 * Uploads an audio blob to convert speech to text.
 */
export async function transcribeAudio(audioBlob: Blob, language?: string): Promise<TranscribeResponse> {
  const formData = new FormData();
  formData.append('file', audioBlob, 'audio.webm');
  if (language) {
    formData.append('language', language);
  }

  const response = await fetch(`${API_BASE_URL}/api/v1/voice/transcribe`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Transcription failed with HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Synthesizes text to speech audio, returning the raw audio Blob.
 */
export async function synthesizeSpeech(req: SynthesizeRequest): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/v1/voice/synthesize`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Speech synthesis failed with HTTP ${response.status}`);
  }

  return response.blob();
}

/**
 * End-to-end voice conversational turn: Audio -> STT -> Agent -> TTS.
 */
export async function sendVoiceChat(
  audioBlob: Blob,
  options?: {
    history?: AgentChatMessage[];
    confirmationToken?: string | null;
    language?: string;
  }
): Promise<VoiceChatResponse> {
  const formData = new FormData();
  formData.append('file', audioBlob, 'audio.webm');

  if (options?.history && options.history.length > 0) {
    formData.append('history', JSON.stringify(options.history));
  }
  if (options?.confirmationToken) {
    formData.append('confirmation_token', options.confirmationToken);
  }
  if (options?.language) {
    formData.append('language', options.language);
  }

  const response = await fetch(`${API_BASE_URL}/api/v1/voice/chat`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Voice chat request failed with HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Cancels an ongoing voice execution turn across all cluster workers via Redis.
 */
export async function cancelVoiceExecution(executionId: string): Promise<VoiceCancelResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/voice/cancel/${encodeURIComponent(executionId)}`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail?.message || errorData.detail || `Cancellation failed with HTTP ${response.status}`);
  }

  return response.json();
}
