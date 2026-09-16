"""
Pydantic Schemas for Long-Term Personal Memory & Personalization (Milestone 11).
Enforces input validation, bounded lengths, allowed category whitelists, and structured response metadata.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


MemoryCategory = Literal[
    "user_preference",
    "user_fact",
    "project_context",
    "workflow_preference",
    "explicit_user_memory",
]

MemoryConfidence = Literal[
    "EXPLICIT",
    "HIGH_CONFIDENCE",
    "MEDIUM_CONFIDENCE",
    "LOW_CONFIDENCE",
]

MemorySource = Literal[
    "explicit_user_request",
    "agent_inference",
    "user_ui",
]


class MemoryBase(BaseModel):
    """Base schema for memory attributes."""
    category: MemoryCategory = Field(
        ...,
        description="Memory classification (user_preference, user_fact, project_context, workflow_preference, explicit_user_memory)",
    )
    key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Normalized key identifier (e.g. 'coding.language', 'project.framework')",
    )
    value: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Stored memory or preference content",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional human-readable context or origin notes",
    )


class MemoryCreateRequest(MemoryBase):
    """Request payload for creating a new memory."""
    confidence: Optional[MemoryConfidence] = Field(
        default="EXPLICIT",
        description="Confidence tier",
    )
    source: Optional[MemorySource] = Field(
        default="user_ui",
        description="Provenance origin",
    )
    source_reference: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional conversation or execution ID reference",
    )
    explicitly_confirmed: Optional[bool] = Field(
        default=False,
        description="Whether explicitly confirmed by user",
    )
    memory_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Arbitrary structured metadata",
    )


class MemoryUpdateRequest(BaseModel):
    """Request payload for updating an existing memory."""
    value: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="Updated memory content",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Updated description or context",
    )
    category: Optional[MemoryCategory] = Field(
        default=None,
        description="Updated category",
    )
    active: Optional[bool] = Field(
        default=None,
        description="Active/inactive state toggle",
    )
    explicitly_confirmed: Optional[bool] = Field(
        default=None,
        description="Explicit confirmation flag",
    )
    confidence: Optional[MemoryConfidence] = Field(
        default=None,
        description="Updated confidence tier",
    )


class MemoryResponse(BaseModel):
    """Full representation of a stored memory entity."""
    id: str
    user_id: str
    category: str
    key: str
    value: str
    description: Optional[str] = None
    confidence: str
    confidence_score: float
    source: str
    source_reference: Optional[str] = None
    explicitly_confirmed: bool
    active: bool
    last_confirmed_at: datetime
    memory_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryListResponse(BaseModel):
    """Paginated list of user memories."""
    status: str = "success"
    total: int
    count: int
    items: List[MemoryResponse]


class MemorySearchResponse(BaseModel):
    """Search results response with relevance scoring."""
    status: str = "success"
    total_found: int
    results: List[MemoryResponse]


class MemoryStatsResponse(BaseModel):
    """Aggregated memory statistics for dashboard visualization."""
    total_memories: int
    active_memories: int
    inactive_memories: int
    memory_enabled: bool
    by_category: Dict[str, int]
    by_confidence: Dict[str, int]
