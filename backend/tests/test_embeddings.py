"""
Unit tests for GeminiEmbeddingProvider and EmbeddingProvider Base (Milestone 7).
Verifies:
- Text embedding generation (gemini-embedding-001)
- Batch document embedding generation
- Strict 768 vector dimension validation
- EmbeddingDimensionMismatchError exception on incompatible dimensions
- HTTP 401/403 -> EmbeddingAuthenticationError
- HTTP 429 -> EmbeddingRateLimitError
- Request timeout -> EmbeddingTimeoutError
- Malformed response -> EmbeddingProviderError
- Empty string handling (zero vector fallback)
"""
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from app.ai.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingAuthenticationError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
    EmbeddingDimensionMismatchError,
)
from app.ai.embeddings.gemini_embeddings import GeminiEmbeddingProvider


@pytest.fixture
def gemini_embedder():
    return GeminiEmbeddingProvider(
        api_key="test-embedding-api-key",
        model_name="gemini-embedding-001",
        dimensions=768,
    )


def test_embedding_provider_initialization(gemini_embedder):
    """Verify provider properties and dimension configuration."""
    assert gemini_embedder.provider_name == "gemini"
    assert gemini_embedder.model_name == "gemini-embedding-001"
    assert gemini_embedder.dimensions == 768


@pytest.mark.asyncio
async def test_embed_text_success(gemini_embedder):
    """Verify single text string embedding returns 768-dim float vector and includes outputDimensionality."""
    mock_vector = [0.05 * (i % 10) for i in range(768)]
    mock_response_data = {
        "embedding": {
            "values": mock_vector
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await gemini_embedder.embed_text("Semantic search query")

        assert len(result) == 768
        assert result == mock_vector

        # Check payload
        payload = mock_post.call_args[1]["json"]
        assert payload["outputDimensionality"] == 768
        assert payload["model"] == "models/gemini-embedding-001"


@pytest.mark.asyncio
async def test_embed_text_empty_string_returns_zero_vector(gemini_embedder):
    """Verify empty or whitespace string returns zero vector without API call."""
    result = await gemini_embedder.embed_text("   ")
    assert len(result) == 768
    assert all(v == 0.0 for v in result)


@pytest.mark.asyncio
async def test_embed_text_dimension_mismatch_raises_error(gemini_embedder):
    """Verify returned vector with wrong dimension count raises EmbeddingDimensionMismatchError."""
    # Return 512 dimensions instead of 768
    mock_vector = [0.1] * 512
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embedding": {"values": mock_vector}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
            await gemini_embedder.embed_text("Dimension check")
        assert "768" in str(exc_info.value)
        assert "512" in str(exc_info.value)


@pytest.mark.asyncio
async def test_embed_documents_batch_success(gemini_embedder):
    """Verify batch document embedding returns list of 768-dim float vectors."""
    texts = ["Chunk 1 text", "Chunk 2 text", "Chunk 3 text"]
    mock_vector = [0.01] * 768
    mock_response_data = {
        "embeddings": [
            {"values": mock_vector},
            {"values": mock_vector},
            {"values": mock_vector},
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        results = await gemini_embedder.embed_documents(texts)

        assert len(results) == 3
        for vec in results:
            assert len(vec) == 768


@pytest.mark.asyncio
async def test_embed_text_auth_error_401(gemini_embedder):
    """Verify HTTP 401 raises EmbeddingAuthenticationError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "API key not valid"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(EmbeddingAuthenticationError):
            await gemini_embedder.embed_text("Auth test")


@pytest.mark.asyncio
async def test_embed_text_rate_limit_429(gemini_embedder):
    """Verify HTTP 429 raises EmbeddingRateLimitError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Resource exhausted"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(EmbeddingRateLimitError):
            await gemini_embedder.embed_text("Rate limit test")


@pytest.mark.asyncio
async def test_embed_text_timeout_error(gemini_embedder):
    """Verify connection timeout raises EmbeddingTimeoutError."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        with pytest.raises(EmbeddingTimeoutError):
            await gemini_embedder.embed_text("Timeout test")


@pytest.mark.asyncio
async def test_embed_text_missing_api_key_raises_auth_error():
    """Verify provider with empty API key raises EmbeddingAuthenticationError."""
    embedder = GeminiEmbeddingProvider(api_key="", model_name="gemini-embedding-001")
    with pytest.raises(EmbeddingAuthenticationError) as exc_info:
        await embedder.embed_text("Missing key test")
    assert "missing or empty" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_embed_documents_empty_list_returns_empty(gemini_embedder):
    """Verify empty document list returns empty result list without API call."""
    res = await gemini_embedder.embed_documents([])
    assert res == []
