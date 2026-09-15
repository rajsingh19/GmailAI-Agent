"""
Abstract Embedding Provider interface for Personal Knowledge RAG (Milestone 7).
Defines normalized embedding exceptions, dimension constraints, and async batching methods.
"""
from abc import ABC, abstractmethod
from typing import List


class EmbeddingProviderError(Exception):
    """Base exception for all embedding generation and provider errors."""
    pass


class EmbeddingAuthenticationError(EmbeddingProviderError):
    """Raised when embedding provider API credentials are missing, invalid, or unauthorized."""
    pass


class EmbeddingRateLimitError(EmbeddingProviderError):
    """Raised when embedding provider rate limits or quotas are exceeded (HTTP 429)."""
    pass


class EmbeddingTimeoutError(EmbeddingProviderError):
    """Raised when an embedding API call times out."""
    pass


class EmbeddingDimensionMismatchError(EmbeddingProviderError):
    """Raised when an embedding provider returns a vector with unexpected dimension count."""
    pass


class EmbeddingProvider(ABC):
    """
    Abstract interface for generating vector embeddings from text strings.
    Model-agnostic and provider-swappable.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider (e.g., 'gemini')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier (e.g., 'text-embedding-004')."""
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Vector dimension count (e.g., 768)."""
        pass

    @abstractmethod
    async def embed_text(self, text: str, timeout: float = 15.0) -> List[float]:
        """
        Generates an embedding vector for a single query or text snippet.
        Returns a float array of length matching self.dimensions.
        """
        pass

    @abstractmethod
    async def embed_documents(self, texts: List[str], timeout: float = 30.0) -> List[List[float]]:
        """
        Generates embedding vectors for a batch of document chunks.
        Returns a list of float arrays, each of length matching self.dimensions.
        """
        pass
