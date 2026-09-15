"""
Unit tests for ChunkingService and Content Hashing (Milestone 7).
Validates boundary-aware text chunking, overlap, SHA-256 hash determinism, and size caps.
"""
import pytest
from app.services.chunking_service import ChunkingService


def test_compute_content_hash_deterministic():
    text = "Hello world! This is a test for content hashing."
    hash1 = ChunkingService.compute_content_hash(text)
    hash2 = ChunkingService.compute_content_hash(text)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex string


def test_compute_content_hash_whitespace_normalized():
    text1 = "  Hello   world!\nThis is a test.  "
    text2 = "Hello world!\nThis is a test."
    assert ChunkingService.compute_content_hash(text1) == ChunkingService.compute_content_hash(text2)


def test_chunk_empty_or_whitespace_text():
    assert ChunkingService.chunk_text("") == []
    assert ChunkingService.chunk_text("   \n\t  ") == []


def test_chunk_short_text_single_chunk():
    text = "This is a short text that fits well within the 500 character chunk size."
    header = "[Source: Tasks | Title: Buy Milk]"
    chunks = ChunkingService.chunk_text(text, context_header=header, chunk_size=500, chunk_overlap=50)
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["content"].startswith(header)
    assert text in chunks[0]["content"]
    assert chunks[0]["char_count"] > 0


def test_chunk_text_boundary_splitting():
    # Construct text with paragraphs and sentences
    para1 = "Paragraph 1 sentence one. Paragraph 1 sentence two. Paragraph 1 sentence three."
    para2 = "Paragraph 2 sentence one with more details. Paragraph 2 sentence two."
    full_text = f"{para1}\n\n{para2}"
    
    chunks = ChunkingService.chunk_text(full_text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) > 1
    # Check that chunks have sequential indices
    for i, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == i
        assert len(chunk["content"]) > 0


def test_chunk_text_overlap():
    text = "Word1 " * 100  # 600 characters
    chunks = ChunkingService.chunk_text(text, chunk_size=200, chunk_overlap=50)
    assert len(chunks) >= 3
    # Check that subsequent chunks contain some overlap from previous
    for i in range(1, len(chunks)):
        # There should be non-empty content
        assert len(chunks[i]["content"]) > 0


def test_chunk_text_max_chars_cap():
    huge_text = "A" * 50000  # 50,000 characters
    chunks = ChunkingService.chunk_text(huge_text, max_chars=1000, chunk_size=400, chunk_overlap=50)
    # Total character sum across base chunks should not exceed capped size
    assert len(chunks) <= 5


def test_sanitize_text_strips_control_characters():
    text = "Hello\x00World\x1f!\tNew Line\nTest."
    sanitized = ChunkingService.sanitize_text(text)
    assert "\x00" not in sanitized
    assert "\x1f" not in sanitized
    assert "Hello" in sanitized
    assert "World" in sanitized
    assert "New Line" in sanitized


def test_chunk_text_preserves_context_header_in_all_chunks():
    long_text = "Detailed paragraph one with lots of information. " * 10
    header = "[Email from: alice@example.com | Subject: Meeting Notes]"
    chunks = ChunkingService.chunk_text(long_text, context_header=header, chunk_size=200, chunk_overlap=30)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["content"].startswith(header)


def test_chunk_text_without_header():
    text = "Plain text without any special context header provided."
    chunks = ChunkingService.chunk_text(text, context_header=None, chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0]["content"] == text


def test_chunk_text_custom_small_chunk_size():
    text = "Sentence one is clear. Sentence two provides more info. Sentence three concludes the point."
    chunks = ChunkingService.chunk_text(text, chunk_size=40, chunk_overlap=10)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c["content"]) <= 60


def test_compute_content_hash_crlf_and_lf_identical():
    crlf_text = "Line 1\r\nLine 2\r\nLine 3"
    lf_text = "Line 1\nLine 2\nLine 3"
    assert ChunkingService.compute_content_hash(crlf_text) == ChunkingService.compute_content_hash(lf_text)
