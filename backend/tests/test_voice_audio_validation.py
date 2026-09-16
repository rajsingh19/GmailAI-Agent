"""
Tests for Strict Audio Validation and Anti-Spoofing (Milestone 10).
Verifies:
- Valid container format validation (WAV, WebM, Ogg, MP3)
- Detection of MIME type spoofing (e.g. WAV declared with WebM payload)
- Malformed magic byte rejection
- Size boundary enforcement (payload too large)
- Duration boundary enforcement
- Header parameter normalization (e.g. audio/webm;codecs=opus)
- Empty payload rejection
- Minimum header length decodability checks
"""

import struct
import pytest

from app.voice.audio_validator import (
    AudioDurationError,
    AudioFormatError,
    AudioSizeError,
    detect_container_format,
    estimate_wav_duration_seconds,
    validate_audio_payload,
)
from app.voice.providers.mock_tts import _generate_valid_wav_bytes


def _make_dummy_webm() -> bytes:
    # EBML magic \x1a\x45\xdf\xa3 followed by minimum bytes
    return b"\x1a\x45\xdf\xa3" + b"\x00" * 30


def _make_dummy_ogg() -> bytes:
    # OggS magic followed by minimum 28 bytes header
    return b"OggS" + b"\x00" * 30


def _make_dummy_mp3() -> bytes:
    # ID3v2 tag header
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 20


def test_validate_valid_wav_audio():
    wav_bytes = _generate_valid_wav_bytes(duration_seconds=1.0)
    canonical = validate_audio_payload(wav_bytes, "audio/wav")
    assert canonical == "audio/wav"


def test_validate_valid_webm_audio():
    webm_bytes = _make_dummy_webm()
    canonical = validate_audio_payload(webm_bytes, "audio/webm")
    assert canonical == "audio/webm"


def test_validate_valid_ogg_audio():
    ogg_bytes = _make_dummy_ogg()
    canonical = validate_audio_payload(ogg_bytes, "audio/ogg")
    assert canonical == "audio/ogg"


def test_validate_valid_mp3_audio():
    mp3_bytes = _make_dummy_mp3()
    canonical = validate_audio_payload(mp3_bytes, "audio/mp3")
    assert canonical == "audio/mp3"


def test_empty_audio_payload_raises_audio_format_error():
    with pytest.raises(AudioFormatError, match="Empty audio payload"):
        validate_audio_payload(b"", "audio/wav")


def test_unsupported_mime_type_raises_audio_format_error():
    wav_bytes = _generate_valid_wav_bytes(duration_seconds=0.5)
    with pytest.raises(AudioFormatError, match="Unsupported audio content-type"):
        validate_audio_payload(wav_bytes, "video/mp4")


def test_container_magic_byte_spoofing_wav_declared_but_webm_bytes():
    webm_bytes = _make_dummy_webm()
    with pytest.raises(AudioFormatError, match="Potential spoofing detected"):
        validate_audio_payload(webm_bytes, "audio/wav")


def test_corrupted_magic_bytes_rejected():
    corrupt_bytes = b"NOT_A_REAL_HEADER_1234567890"
    with pytest.raises(AudioFormatError, match="Audio container signature unrecognized"):
        validate_audio_payload(corrupt_bytes, "audio/wav")


def test_payload_exceeding_max_bytes_raises_audio_size_error():
    wav_bytes = _generate_valid_wav_bytes(duration_seconds=0.5)
    with pytest.raises(AudioSizeError, match="exceeds maximum limit"):
        validate_audio_payload(wav_bytes, "audio/wav", max_bytes=100)


def test_wav_duration_estimation():
    # 2 seconds at 16000Hz mono 16-bit
    wav_bytes = _generate_valid_wav_bytes(duration_seconds=2.0)
    dur = estimate_wav_duration_seconds(wav_bytes)
    assert dur is not None
    assert 1.9 <= dur <= 2.1


def test_wav_duration_exceeding_max_duration_rejected():
    wav_bytes = _generate_valid_wav_bytes(duration_seconds=5.0)
    with pytest.raises(AudioDurationError, match="Audio duration .* exceeds maximum limit"):
        validate_audio_payload(wav_bytes, "audio/wav", max_duration_seconds=2)


def test_mime_type_with_parameters_cleaned():
    webm_bytes = _make_dummy_webm()
    canonical = validate_audio_payload(webm_bytes, "audio/webm; codecs=opus")
    assert canonical == "audio/webm"
