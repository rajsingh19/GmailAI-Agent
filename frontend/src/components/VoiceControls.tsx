import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Mic,
  Square,
  X,
  Volume2,
  VolumeX,
  Play,
  Pause,
  AlertCircle,
  Radio,
} from 'lucide-react';

interface VoiceControlsProps {
  onAudioRecorded: (audioBlob: Blob) => void;
  disabled?: boolean;
  isProcessing?: boolean;
  onCancelProcessing?: () => void;
  lastAudioBase64?: string | null;
  lastAudioMimeType?: string | null;
  ttsStatus?: 'success' | 'degraded' | 'disabled';
}

export const VoiceControls: React.FC<VoiceControlsProps> = ({
  onAudioRecorded,
  disabled = false,
  isProcessing = false,
  onCancelProcessing,
  lastAudioBase64,
  lastAudioMimeType = 'audio/wav',
  ttsStatus,
}) => {
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [recordSeconds, setRecordSeconds] = useState<number>(0);
  const [micError, setMicError] = useState<string | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState<boolean>(false);
  const [isMuted, setIsMuted] = useState<boolean>(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerIntervalRef = useRef<number | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Auto-play synthesized speech when new base64 audio arrives
  useEffect(() => {
    if (lastAudioBase64 && !isMuted) {
      const mime = lastAudioMimeType || 'audio/wav';
      const audioSrc = `data:${mime};base64,${lastAudioBase64}`;
      if (audioElementRef.current) {
        audioElementRef.current.src = audioSrc;
        audioElementRef.current
          .play()
          .then(() => setIsPlayingAudio(true))
          .catch((err) => {
            console.warn('Auto-play prevented by browser policy:', err);
            setIsPlayingAudio(false);
          });
      }
    }
  }, [lastAudioBase64, lastAudioMimeType, isMuted]);

  const cleanupRecording = useCallback(() => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    mediaRecorderRef.current = null;
    setIsRecording(false);
    setRecordSeconds(0);
  }, []);

  const startRecording = async () => {
    setMicError(null);
    audioChunksRef.current = [];

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setMicError('Microphone audio capture is not supported in this browser.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Select supported MIME type
      let mimeType = 'audio/webm;codecs=opus';
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        if (MediaRecorder.isTypeSupported('audio/webm')) {
          mimeType = 'audio/webm';
        } else if (MediaRecorder.isTypeSupported('audio/ogg')) {
          mimeType = 'audio/ogg';
        } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
          mimeType = 'audio/mp4';
        } else {
          mimeType = '';
        }
      }

      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        if (audioChunksRef.current.length > 0) {
          const finalType = recorder.mimeType || 'audio/webm';
          const audioBlob = new Blob(audioChunksRef.current, { type: finalType });
          onAudioRecorded(audioBlob);
        }
        cleanupRecording();
      };

      recorder.start(250); // Slice chunks every 250ms
      setIsRecording(true);
      setRecordSeconds(0);

      // Start elapsed timer (limit to 60s)
      const startTime = Date.now();
      timerIntervalRef.current = window.setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        setRecordSeconds(elapsed);
        if (elapsed >= 60) {
          // Exceeded max duration limit, stop recording automatically
          recorder.stop();
        }
      }, 500);
    } catch (err: any) {
      console.error('Failed to acquire microphone:', err);
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setMicError('Microphone access was denied. Please allow microphone permissions.');
      } else {
        setMicError(err.message || 'Unable to access microphone.');
      }
      cleanupRecording();
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
    }
  };

  const cancelRecording = () => {
    audioChunksRef.current = [];
    cleanupRecording();
  };

  const toggleAudioPlayback = () => {
    if (!audioElementRef.current || !lastAudioBase64) return;
    if (isPlayingAudio) {
      audioElementRef.current.pause();
      setIsPlayingAudio(false);
    } else {
      audioElementRef.current
        .play()
        .then(() => setIsPlayingAudio(true))
        .catch(() => setIsPlayingAudio(false));
    }
  };

  const formatSeconds = (sec: number): string => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div className="flex items-center gap-2">
      {/* Hidden audio element for speech playback */}
      <audio
        ref={audioElementRef}
        onEnded={() => setIsPlayingAudio(false)}
        onError={() => setIsPlayingAudio(false)}
        className="hidden"
      />

      {/* Recording in progress overlay bar */}
      {isRecording ? (
        <div className="flex items-center gap-2 bg-red-950/60 border border-red-500/40 rounded-xl px-3 py-1.5 animate-pulse">
          <Radio className="w-4 h-4 text-red-400 animate-spin" />
          <span className="text-xs font-mono font-semibold text-red-300">
            REC {formatSeconds(recordSeconds)} / 1:00
          </span>

          {/* Pulsing audio bars */}
          <div className="flex items-center gap-0.5 h-3 px-1">
            <span className="w-1 bg-red-400 rounded-full animate-bounce h-2" style={{ animationDelay: '0ms' }} />
            <span className="w-1 bg-red-400 rounded-full animate-bounce h-3" style={{ animationDelay: '150ms' }} />
            <span className="w-1 bg-red-400 rounded-full animate-bounce h-1.5" style={{ animationDelay: '300ms' }} />
            <span className="w-1 bg-red-400 rounded-full animate-bounce h-3" style={{ animationDelay: '75ms' }} />
          </div>

          <button
            type="button"
            onClick={stopRecording}
            className="p-1 rounded-lg bg-red-600 hover:bg-red-500 text-white transition-colors cursor-pointer"
            title="Done Speaking"
          >
            <Square className="w-3.5 h-3.5 fill-current" />
          </button>
          <button
            type="button"
            onClick={cancelRecording}
            className="p-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
            title="Discard Recording"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ) : isProcessing ? (
        /* Processing voice turn state */
        <div className="flex items-center gap-2 bg-indigo-950/60 border border-indigo-500/40 rounded-xl px-3 py-1.5">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping" />
          <span className="text-xs text-indigo-300 font-medium">Processing voice...</span>
          {onCancelProcessing && (
            <button
              type="button"
              onClick={onCancelProcessing}
              className="p-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition-colors cursor-pointer"
              title="Cancel voice request"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
      ) : (
        /* Idle mic button */
        <button
          type="button"
          onClick={startRecording}
          disabled={disabled}
          className="h-[52px] w-[52px] rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 flex items-center justify-center transition-all disabled:opacity-50 disabled:hover:bg-slate-800 cursor-pointer shadow-sm group"
          title="Voice input (Click to talk)"
        >
          <Mic className="w-5 h-5 text-indigo-400 group-hover:text-indigo-300 transition-colors" />
        </button>
      )}

      {/* TTS Audio Controls if previous response had speech */}
      {lastAudioBase64 && !isRecording && (
        <div className="flex items-center gap-1 bg-slate-800/70 border border-slate-700/60 rounded-xl px-2 py-1.5">
          <button
            type="button"
            onClick={toggleAudioPlayback}
            className="p-1 text-slate-300 hover:text-white transition-colors cursor-pointer"
            title={isPlayingAudio ? 'Pause Speech' : 'Play Speech'}
          >
            {isPlayingAudio ? (
              <Pause className="w-3.5 h-3.5 text-blue-400" />
            ) : (
              <Play className="w-3.5 h-3.5 text-blue-400" />
            )}
          </button>
          <button
            type="button"
            onClick={() => setIsMuted((prev) => !prev)}
            className="p-1 text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
            title={isMuted ? 'Unmute Speech Auto-play' : 'Mute Speech Auto-play'}
          >
            {isMuted ? (
              <VolumeX className="w-3.5 h-3.5 text-slate-500" />
            ) : (
              <Volume2 className="w-3.5 h-3.5 text-emerald-400" />
            )}
          </button>
        </div>
      )}

      {/* Degradation notice tag if TTS degraded */}
      {ttsStatus === 'degraded' && (
        <span
          className="text-[10px] bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2 py-1 rounded-md"
          title="Speech synthesis was unavailable; text response provided"
        >
          Audio degraded
        </span>
      )}

      {/* Mic permission/access error tooltip */}
      {micError && (
        <div className="text-xs text-rose-400 flex items-center gap-1 bg-rose-950/40 border border-rose-800/50 px-2 py-1 rounded-lg">
          <AlertCircle className="w-3 h-3 flex-shrink-0" />
          <span className="truncate max-w-[200px]">{micError}</span>
        </div>
      )}
    </div>
  );
};
