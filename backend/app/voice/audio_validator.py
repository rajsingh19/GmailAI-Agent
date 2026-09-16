"""
Strict audio container, magic byte, and decodability validator.
Guards against container spoofing, truncated files, and resource exhaustion.
"""
import struct
from typing import Optional, Set
import logging

from app.core.config import settings

logger = logging.getLogger(settings.PROJECT_NAME)

SUPPORTED_MIME_TYPES: Set[str] = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/webm",
    "audio/ogg",
    "audio/opus",
    "audio/mp3",
    "audio/mpeg",
    "audio/m4a",
    "audio/x-m4a",
    "audio/mp4",
}


class AudioValidationError(Exception):
    """Base error for audio validation failures."""
    def __init__(self, message: str, code: str = "INVALID_AUDIO"):
        super().__init__(message)
        self.code = code
        self.message = message


class AudioSizeError(AudioValidationError):
    """Raised when audio payload exceeds size limits (HTTP 413)."""
    def __init__(self, message: str = "Audio file exceeds maximum allowed size"):
        super().__init__(message, code="PAYLOAD_TOO_LARGE")


class AudioFormatError(AudioValidationError):
    """Raised when MIME type is unsupported or magic bytes are spoofed/malformed (HTTP 415 / 400)."""
    def __init__(self, message: str, code: str = "UNSUPPORTED_MEDIA_TYPE"):
        super().__init__(message, code=code)


class AudioDurationError(AudioValidationError):
    """Raised when audio recording length exceeds maximum allowed seconds (HTTP 400)."""
    def __init__(self, message: str = "Audio duration exceeds maximum allowed limit"):
        super().__init__(message, code="AUDIO_TOO_LONG")


def detect_container_format(audio_bytes: bytes) -> Optional[str]:
    """
    Inspects magic bytes to detect real underlying container format.
    Returns canonical format name: 'wav', 'webm', 'ogg', 'mp3', 'm4a', or None if unknown.
    """
    if len(audio_bytes) < 4:
        return None

    # 1. WAV: starts with RIFF and has WAVE at offset 8
    if audio_bytes.startswith(b"RIFF") and len(audio_bytes) >= 12:
        if audio_bytes[8:12] == b"WAVE":
            return "wav"

    # 2. WebM: EBML header \x1a\x45\xdf\xa3
    if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"

    # 3. Ogg: starts with OggS
    if audio_bytes.startswith(b"OggS"):
        return "ogg"

    # 4. MP3: starts with ID3v2 tag or MPEG frame sync
    if audio_bytes.startswith(b"ID3"):
        return "mp3"
    if len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0:
        return "mp3"

    # 5. M4A / MP4: offset 4:8 is ftyp
    if len(audio_bytes) >= 8 and audio_bytes[4:8] == b"ftyp":
        return "m4a"

    return None


def estimate_wav_duration_seconds(audio_bytes: bytes) -> Optional[float]:
    """Extracts duration from standard PCM WAV header if available."""
    if len(audio_bytes) < 44 or not audio_bytes.startswith(b"RIFF") or audio_bytes[8:12] != b"WAVE":
        return None
    try:
        channels, sample_rate, byte_rate = struct.unpack("<HII", audio_bytes[22:32])
        if byte_rate > 0 and len(audio_bytes) > 44:
            data_size = len(audio_bytes) - 44
            return round(data_size / byte_rate, 2)
    except Exception:
        return None
    return None


def validate_audio_payload(
    audio_bytes: bytes,
    declared_content_type: str,
    max_bytes: Optional[int] = None,
    max_duration_seconds: Optional[int] = None,
) -> str:
    """
    Validates:
    1. Payload size constraint.
    2. Declared MIME type is permitted.
    3. Container magic bytes match declared type (anti-spoofing).
    4. Structural decodability / minimum container header size.
    5. Duration limits (where header allows calculation).

    Returns:
        canonical_content_type (str)
    """
    limit_bytes = max_bytes or settings.MAX_AUDIO_BYTES
    limit_duration = max_duration_seconds or settings.MAX_AUDIO_DURATION_SECONDS

    # 1. Size bounds check
    if not audio_bytes or len(audio_bytes) == 0:
        raise AudioFormatError("Empty audio payload received.", code="EMPTY_PAYLOAD")

    if len(audio_bytes) > limit_bytes:
        raise AudioSizeError(
            f"Audio payload size ({len(audio_bytes)} bytes) exceeds maximum limit of {limit_bytes} bytes."
        )

    # 2. Declared content-type check
    clean_type = declared_content_type.split(";")[0].strip().lower()
    if clean_type not in SUPPORTED_MIME_TYPES:
        raise AudioFormatError(
            f"Unsupported audio content-type: '{clean_type}'. Allowed types: {', '.join(sorted(SUPPORTED_MIME_TYPES))}",
            code="UNSUPPORTED_MEDIA_TYPE",
        )

    # 3. Magic bytes / container inspection
    detected = detect_container_format(audio_bytes)
    if not detected:
        raise AudioFormatError(
            "Audio container signature unrecognized or corrupted. Malformed audio payload.",
            code="MALFORMED_AUDIO",
        )

    # Verify declared MIME type matches real container
    mime_to_detected = {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
        "audio/mp3": "mp3",
        "audio/mpeg": "mp3",
        "audio/m4a": "m4a",
        "audio/x-m4a": "m4a",
        "audio/mp4": "m4a",
    }
    expected_detected = mime_to_detected.get(clean_type)
    if expected_detected and expected_detected != detected:
        raise AudioFormatError(
            f"Audio container mismatch: declared '{clean_type}' but payload signature is '{detected}'. Potential spoofing detected.",
            code="CONTAINER_SPOOFED",
        )

    # 4. Decodability & Minimum length checks
    if detected == "wav":
        if len(audio_bytes) < 44:
            raise AudioFormatError("WAV container header truncated (< 44 bytes).", code="MALFORMED_AUDIO")
        # Check RIFF declared size vs actual file
        try:
            riff_size = struct.unpack("<I", audio_bytes[4:8])[0]
            # File should have at least 8 bytes for RIFF header + declared size (with a little tolerance for metadata)
            if len(audio_bytes) < riff_size:
                # Corrupted or severely truncated
                raise AudioFormatError("WAV container data is truncated.", code="MALFORMED_AUDIO")
        except struct.error:
            raise AudioFormatError("WAV container header corrupted.", code="MALFORMED_AUDIO")

        wav_duration = estimate_wav_duration_seconds(audio_bytes)
        if wav_duration and wav_duration > limit_duration:
            raise AudioDurationError(
                f"Audio duration ({wav_duration:.1f}s) exceeds maximum limit of {limit_duration}s."
            )

    elif detected == "webm":
        if len(audio_bytes) < 12:
            raise AudioFormatError("WebM container header truncated (< 12 bytes).", code="MALFORMED_AUDIO")

    elif detected == "ogg":
        if len(audio_bytes) < 28:
            raise AudioFormatError("Ogg container header truncated (< 28 bytes).", code="MALFORMED_AUDIO")

    elif detected == "mp3":
        if len(audio_bytes) < 10:
            raise AudioFormatError("MP3 container header truncated (< 10 bytes).", code="MALFORMED_AUDIO")

    return clean_type
