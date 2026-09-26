"""
Google Gemini Embedding Provider implementation (Milestone 7).
Uses Google Generative Language REST API for gemini-embedding-001 (768 dimensions).
"""
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.ai.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingAuthenticationError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
    EmbeddingDimensionMismatchError,
)

logger = logging.getLogger(__name__)


class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Google Gemini REST client for text embeddings (gemini-embedding-001).
    Enforces output dimension validation, batching, and error mapping.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        dimensions: Optional[int] = None,
    ):
        self._api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self._model_name = model_name or settings.effective_embedding_model
        self._dimensions = dimensions or settings.EMBEDDING_DIMENSIONS

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _validate_dimension(self, vector: List[float], source_label: str = "embedding") -> None:
        """Ensures the generated embedding vector strictly matches configured dimension size."""
        if len(vector) != self._dimensions:
            err_msg = (
                f"Embedding dimension mismatch: expected {self._dimensions} dimensions, "
                f"but received {len(vector)} dimensions for {source_label}."
            )
            logger.error(err_msg)
            raise EmbeddingDimensionMismatchError(err_msg)

    async def embed_text(self, text: str, timeout: float = 15.0) -> List[float]:
        """Generates embedding for a single text string."""
        if not self._api_key:
            raise EmbeddingAuthenticationError(
                "GEMINI_API_KEY is missing or empty. Please configure backend environment settings."
            )

        clean_text = text.strip()
        if not clean_text:
            # Return zero vector for empty strings
            return [0.0] * self._dimensions

        url = f"{self.BASE_URL}/models/{self._model_name}:embedContent"
        params = {"key": self._api_key}
        payload: Dict[str, Any] = {
            "model": f"models/{self._model_name}",
            "content": {"parts": [{"text": clean_text}]},
            "outputDimensionality": self._dimensions,
        }
        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, params=params, json=payload, headers=headers)

            if response.status_code in (401, 403):
                raise EmbeddingAuthenticationError(
                    f"Gemini Embedding API authentication failed (HTTP {response.status_code})."
                )
            if response.status_code == 429:
                raise EmbeddingRateLimitError("Gemini Embedding API rate limit or quota exceeded.")
            if response.status_code != 200:
                logger.warning("Gemini Embedding API error HTTP %d: %s", response.status_code, response.text[:200])
                raise EmbeddingProviderError(f"Gemini Embedding API returned HTTP {response.status_code}.")

            data = response.json()
            embedding_obj = data.get("embedding", {})
            values = embedding_obj.get("values", [])

            if not values:
                raise EmbeddingProviderError("Gemini returned empty embedding values.")

            self._validate_dimension(values, source_label="single query")
            return values

        except httpx.TimeoutException as exc:
            logger.warning("Gemini embedding request timed out after %.1f seconds", timeout)
            raise EmbeddingTimeoutError(f"Gemini embedding request timed out after {timeout}s.") from exc
        except (
            EmbeddingProviderError,
            EmbeddingAuthenticationError,
            EmbeddingRateLimitError,
            EmbeddingTimeoutError,
            EmbeddingDimensionMismatchError,
        ):
            raise
        except Exception as exc:
            logger.exception("Unexpected error during Gemini embedding generation: %s", exc)
            raise EmbeddingProviderError(f"Failed to generate embedding: {exc}") from exc

    async def embed_documents(self, texts: List[str], timeout: float = 30.0) -> List[List[float]]:
        """
        Generates embeddings for a batch of document texts.
        Automatically chunks requests into batches of size settings.EMBEDDING_BATCH_SIZE.
        """
        if not texts:
            return []

        if not self._api_key:
            raise EmbeddingAuthenticationError(
                "GEMINI_API_KEY is missing or empty. Please configure backend environment settings."
            )

        all_embeddings: List[List[float]] = []
        batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = await self._embed_batch(batch, timeout=timeout)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch(self, texts: List[str], timeout: float) -> List[List[float]]:
        """Internal helper to execute a single batchEmbedContents request."""
        url = f"{self.BASE_URL}/models/{self._model_name}:batchEmbedContents"
        params = {"key": self._api_key}

        requests_payload = [
            {
                "model": f"models/{self._model_name}",
                "content": {"parts": [{"text": t.strip() or " "}]},
                "outputDimensionality": self._dimensions,
            }
            for t in texts
        ]

        payload = {"requests": requests_payload}
        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, params=params, json=payload, headers=headers)

            if response.status_code in (401, 403):
                raise EmbeddingAuthenticationError(
                    f"Gemini Embedding API authentication failed (HTTP {response.status_code})."
                )
            if response.status_code == 429:
                raise EmbeddingRateLimitError("Gemini Embedding API rate limit or quota exceeded.")
            if response.status_code != 200:
                logger.warning("Gemini Embedding API error HTTP %d: %s", response.status_code, response.text[:200])
                raise EmbeddingProviderError(f"Gemini Embedding API returned HTTP {response.status_code}.")

            data = response.json()
            raw_embeddings = data.get("embeddings", [])

            if len(raw_embeddings) != len(texts):
                raise EmbeddingProviderError(
                    f"Expected {len(texts)} embeddings in batch, but received {len(raw_embeddings)}."
                )

            batch_results: List[List[float]] = []
            for idx, item in enumerate(raw_embeddings):
                values = item.get("values", [])
                if not values:
                    raise EmbeddingProviderError(f"Batch embedding at index {idx} contained empty values.")
                self._validate_dimension(values, source_label=f"chunk_{idx}")
                batch_results.append(values)

            return batch_results

        except httpx.TimeoutException as exc:
            logger.warning("Gemini batch embedding request timed out after %.1f seconds", timeout)
            raise EmbeddingTimeoutError(f"Gemini batch embedding request timed out after {timeout}s.") from exc
        except (
            EmbeddingProviderError,
            EmbeddingAuthenticationError,
            EmbeddingRateLimitError,
            EmbeddingTimeoutError,
            EmbeddingDimensionMismatchError,
        ):
            raise
        except Exception as exc:
            logger.exception("Unexpected error during Gemini batch embedding generation: %s", exc)
            raise EmbeddingProviderError(f"Failed to generate batch embeddings: {exc}") from exc
