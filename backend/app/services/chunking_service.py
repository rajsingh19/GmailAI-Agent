"""
Chunking and Content Hashing Service for Personal Knowledge RAG (Milestone 7).
Provides deterministic text splitting, boundary preservation, context headers, and SHA-256 deduplication.
"""
import hashlib
import re
import logging
from typing import List, Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class ChunkingService:
    """
    Deterministic text splitter and content hasher for RAG knowledge ingestion.
    """

    @staticmethod
    def sanitize_text(text: str) -> str:
        """
        Strips non-printable control characters while preserving newlines and tabs.
        """
        if not text:
            return ""
        # Remove ASCII control characters except \t and \n
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """
        Computes SHA-256 hex digest of normalized content string.
        Normalizes CRLF and trailing whitespace to ensure cross-platform determinism.
        """
        normalized = re.sub(r"\r\n", "\n", content.strip())
        normalized = re.sub(r"[ \t]+", " ", normalized)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def chunk_text(
        text: str,
        context_header: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Splits raw document text into deterministic overlapping chunks with boundary preservation.
        
        Args:
            text: Raw sanitized text content
            context_header: Optional provenance prefix (e.g. '[Source: Gmail | Subject: Project]')
            chunk_size: Target character length per chunk (default from config: 500)
            chunk_overlap: Overlap between consecutive chunks (default from config: 75)
            max_chars: Upper bound limit on total document length (default: 20,000)
        
        Returns:
            List of chunk dicts: [{"chunk_index": 0, "content": "...", "token_count": N}]
        """
        target_chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
        target_overlap = chunk_overlap or settings.RAG_CHUNK_OVERLAP
        target_max_chars = max_chars or settings.MAX_DOCUMENT_INGEST_CHARS

        # 1. Truncate oversized document
        clean_text = text.strip()[:target_max_chars]
        if not clean_text:
            return []

        # 2. Format context header
        header_prefix = f"{context_header.strip()}\n\n" if context_header and context_header.strip() else ""

        # If entire text fits in one chunk
        if len(clean_text) <= target_chunk_size:
            full_content = f"{header_prefix}{clean_text}" if header_prefix else clean_text
            return [
                {
                    "chunk_index": 0,
                    "content": full_content,
                    "token_count": max(1, len(full_content) // 4),
                    "char_count": len(full_content),
                }
            ]

        # 3. Boundary-aware sliding window
        chunks: List[str] = []
        start_idx = 0
        text_len = len(clean_text)

        while start_idx < text_len:
            end_idx = min(start_idx + target_chunk_size, text_len)

            if end_idx < text_len:
                # Look backwards for paragraph break
                para_break = clean_text.rfind("\n\n", start_idx + target_overlap, end_idx)
                if para_break != -1:
                    end_idx = para_break + 2
                else:
                    # Look backwards for newline
                    line_break = clean_text.rfind("\n", start_idx + target_overlap, end_idx)
                    if line_break != -1:
                        end_idx = line_break + 1
                    else:
                        # Look backwards for sentence end
                        sentence_match = re.search(r"[\.\?\!]\s", clean_text[start_idx + target_overlap : end_idx])
                        if sentence_match:
                            # Adjust index to after sentence punctuation
                            last_punct = clean_text[start_idx + target_overlap : end_idx].rfind(". ")
                            if last_punct != -1:
                                end_idx = start_idx + target_overlap + last_punct + 2
                            else:
                                space_idx = clean_text.rfind(" ", start_idx + target_overlap, end_idx)
                                if space_idx != -1:
                                    end_idx = space_idx + 1

            chunk_slice = clean_text[start_idx:end_idx].strip()
            if chunk_slice:
                chunks.append(chunk_slice)

            if end_idx >= text_len:
                break

            # Advance sliding window by (end_idx - target_overlap)
            next_start = max(start_idx + 1, end_idx - target_overlap)
            start_idx = next_start

        # 4. Construct final chunk dicts with headers
        structured_chunks: List[Dict[str, Any]] = []
        for idx, chk in enumerate(chunks):
            chunk_with_header = f"{header_prefix}{chk}" if header_prefix else chk
            structured_chunks.append({
                "chunk_index": idx,
                "content": chunk_with_header,
                "token_count": max(1, len(chunk_with_header) // 4),
                "char_count": len(chunk_with_header),
            })

        return structured_chunks
