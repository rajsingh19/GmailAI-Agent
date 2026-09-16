"""
Pydantic Schemas for Personalization Intelligence & Policy Layer (Milestone 12).
Enforces strict enum validation, bounded request payloads, and sanitized explainability metadata.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class PersonalizationLevel(str, Enum):
    """
    Personalization strength levels. Controls context scope and density only.
    Strictly uppercase. Never grants permissions or authority.
    """
    NONE = "NONE"          # Zero personalization context injected
    LOW = "LOW"            # Constrained response-style hints only (max 1 item / 250 chars)
    MEDIUM = "MEDIUM"      # Style + project context + top technical preferences (max 3 items / 600 chars)
    HIGH = "HIGH"          # Comprehensive: style + project + workflow habits (max 5 items / 1,000 chars)


class PersonalizationConfigResponse(BaseModel):
    """Current personalization settings for the authenticated user."""
    personalization_enabled: bool = Field(
        ...,
        description="Master toggle for Personalization Intelligence (Opt-in Default: False)",
    )
    personalization_level: PersonalizationLevel = Field(
        ...,
        description="Active personalization level (NONE, LOW, MEDIUM, HIGH)",
    )
    personalize_response_style: bool = Field(
        ...,
        description="Whether response tone/style adaptation is enabled",
    )
    personalize_project_context: bool = Field(
        ...,
        description="Whether active project stack/conventions are tailored",
    )
    personalize_workflow_habits: bool = Field(
        ...,
        description="Whether recurring task/reminder patterns are suggested",
    )


class PersonalizationConfigOut(PersonalizationConfigResponse):
    """Extended output including memory and session override flags."""
    memory_enabled: Optional[bool] = Field(
        default=False,
        description="Whether underlying M11 long-term memory storage is active",
    )
    session_override_active: Optional[bool] = Field(
        default=False,
        description="Whether an ephemeral session override is currently suppressing personalization",
    )


class PersonalizationConfigUpdate(BaseModel):
    """Update payload for user personalization settings."""
    personalization_enabled: Optional[bool] = Field(
        None,
        description="Master toggle for Personalization Intelligence",
    )
    personalization_level: Optional[PersonalizationLevel] = Field(
        None,
        description="Personalization strength tier (NONE, LOW, MEDIUM, HIGH)",
    )
    personalize_response_style: Optional[bool] = Field(
        None,
        description="Enable/disable response style adaptation",
    )
    personalize_project_context: Optional[bool] = Field(
        None,
        description="Enable/disable project context awareness",
    )
    personalize_workflow_habits: Optional[bool] = Field(
        None,
        description="Enable/disable workflow habit suggestions",
    )

    @field_validator("personalization_level", mode="before")
    @classmethod
    def validate_uppercase_enum(cls, v: Any) -> Any:
        if v is not None and isinstance(v, str):
            v_upper = v.strip().upper()
            if v != v_upper or v_upper not in (PersonalizationLevel.NONE.value, PersonalizationLevel.LOW.value, PersonalizationLevel.MEDIUM.value, PersonalizationLevel.HIGH.value):
                raise ValueError(f"Invalid personalization_level: {v}. Must be strictly uppercase: NONE, LOW, MEDIUM, HIGH")
            return PersonalizationLevel(v_upper)
        return v


class PersonalizationPreviewRequest(BaseModel):
    """Request payload to preview deterministic relevance scoring on a sample query."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Sample user query to test relevance matching against active memories",
    )
    limit: Optional[int] = Field(
        default=10,
        ge=1,
        le=10,
        description="Maximum number of candidate previews to return",
    )


class PersonalizationPreviewItem(BaseModel):
    """Sanitized evaluation result for a candidate memory item. Never contains raw values or secrets."""
    category: str = Field(..., description="Memory category classification")
    key: str = Field(..., description="Normalized key identifier")
    relevance_score: float = Field(..., description="Computed deterministic relevance score")
    is_selected: bool = Field(..., description="Whether score meets the 15.0 threshold and level bound")
    selection_reason: str = Field(..., description="Human-readable deterministic match justification")


class PersonalizationPreviewResponse(BaseModel):
    """Result of deterministic relevance preview calculation."""
    query: str = Field(..., description="Evaluated query")
    items: List[PersonalizationPreviewItem] = Field(default_factory=list, description="Evaluated memory candidate previews")
    personalization_enabled: Optional[bool] = Field(default=None, description="User's master personalization status")
    personalization_level: Optional[PersonalizationLevel] = Field(default=None, description="User's active personalization tier")
    candidate_count: Optional[int] = Field(default=None, description="Total candidate memories evaluated")
    selected_count: Optional[int] = Field(default=None, description="Total memories meeting the threshold and bounds")


class PersonalizationSessionOverrideRequest(BaseModel):
    """Request to activate or clear an ephemeral session-level personalization override."""
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique session or conversation identifier",
    )
    disable_personalization: bool = Field(
        ...,
        description="True to temporarily disable personalization for this session; False to resume",
    )


class PersonalizationSessionOverrideResponse(BaseModel):
    """Confirmation of session override status change."""
    session_id: str = Field(..., description="Session identifier")
    personalization_disabled: bool = Field(..., description="Current session override state")
    message: str = Field(..., description="Status description")


# Backwards-compatible aliases
SessionOverrideRequest = PersonalizationSessionOverrideRequest
SessionOverrideResponse = PersonalizationSessionOverrideResponse


class PersonalizationMetadata(BaseModel):
    """
    Backend-controlled explainability metadata attached to Agent responses.
    Zero raw memory values, secrets, private descriptions, or system prompts.
    """
    level: str = Field(..., description="Personalization level applied during turn")
    applied_keys: List[str] = Field(default_factory=list, description="List of memory keys selected and applied")
    categories: List[str] = Field(default_factory=list, description="Categories of applied memories")
    reason: str = Field(..., description="Sanitized, human-readable summary of applied personalization")
