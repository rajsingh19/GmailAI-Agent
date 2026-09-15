"""
Pydantic Schemas for Personal Knowledge & RAG APIs (Milestone 7).
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class KnowledgeCitation(BaseModel):
    """Structured citation metadata for grounded RAG responses."""
    citation_id: str = Field(..., description="Deterministic citation token (e.g., 'cit_1')")
    source_type: str = Field(..., description="Source system ('gmail', 'calendar', 'task', 'reminder')")
    source_id: str = Field(..., description="External source ID")
    title: str = Field(..., description="Title or subject of the source item")
    similarity_score: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")


class KnowledgeResultItem(BaseModel):
    """Detailed search result excerpt with provenance."""
    citation_id: str
    source_type: str
    source_id: str
    title: str
    snippet: str
    similarity_score: float
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchRequest(BaseModel):
    """Request payload for semantic knowledge search."""
    query: str = Field(..., min_length=1, max_length=500, description="Natural language search query")
    source_type: Optional[str] = Field(default=None, description="Optional source type filter")
    top_k: Optional[int] = Field(default=5, ge=1, le=10, description="Maximum number of excerpts to return")
    similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Minimum similarity threshold")


class KnowledgeSearchResponse(BaseModel):
    """Response payload for semantic knowledge search."""
    status: str
    total_found: int
    results: List[KnowledgeResultItem]
    citations: List[KnowledgeCitation]


class SourceStatusSummary(BaseModel):
    """Indexing summary for a specific source category."""
    document_count: int
    last_indexed: Optional[str] = None


class KnowledgeStatusResponse(BaseModel):
    """Response payload for knowledge base status inspection."""
    total_documents: int
    total_chunks: int
    last_indexed: Optional[str] = None
    sources: Dict[str, SourceStatusSummary] = Field(default_factory=dict)
    embedding_model: str
    embedding_dimensions: int


class KnowledgeReindexResponse(BaseModel):
    """Response payload for knowledge reindexing operation."""
    status: str
    documents_processed: int
    documents_indexed: int
    documents_skipped: int
    chunks_created: int
    duration_ms: float
    errors: List[str] = Field(default_factory=list)
