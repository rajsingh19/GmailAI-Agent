"""
Pydantic schemas for LinkedIn Extension token management and job ingestion.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from app.schemas.job import JobResponse, JobMatchAnalysisResponse


class ExtensionTokenStatusResponse(BaseModel):
    """Status of the user's extension token."""
    has_token: bool = Field(..., description="Whether user has an extension token")
    id: Optional[str] = Field(None, description="Extension token identifier")
    token_prefix: Optional[str] = Field(None, description="First few characters of the token for identification (e.g. ext_a1b2...)")
    name: Optional[str] = Field(None, description="Token descriptive name")
    is_active: bool = Field(False, description="Whether the token is currently valid and active")
    last_used_at: Optional[datetime] = Field(None, description="Timestamp when the token was last used for ingestion")
    created_at: Optional[datetime] = Field(None, description="Timestamp when the token was created")
    revoked_at: Optional[datetime] = Field(None, description="Timestamp when token was revoked, if applicable")


class ExtensionTokenCreatedResponse(BaseModel):
    """Response returned when generating a new extension token (raw token is returned ONCE)."""
    id: str = Field(..., description="Extension token ID")
    token_prefix: str = Field(..., description="Token prefix")
    raw_token: str = Field(..., description="Full raw extension token. Store securely; this is never shown again.")
    name: str = Field(..., description="Token name")
    created_at: datetime = Field(..., description="Creation timestamp")
    message: str = Field("Extension token generated successfully. Copy this token into your extension settings.", description="Status message")


class ExtensionTokenRevokeResponse(BaseModel):
    """Response returned when revoking an extension token."""
    success: bool = Field(True, description="Revocation success status")
    message: str = Field("Extension token revoked successfully.", description="Status message")


class LinkedInJobIngestRequest(BaseModel):
    """Payload received from the LinkedIn Browser Extension."""
    job_url: str = Field(..., description="Canonical LinkedIn Job URL (e.g. https://www.linkedin.com/jobs/view/...)")
    job_title: Optional[str] = Field(None, description="Extracted job title")
    company_name: Optional[str] = Field(None, description="Extracted company name")
    location: Optional[str] = Field(None, description="Extracted job location")
    raw_jd_text: str = Field(..., min_length=20, description="Visible text of the job description extracted from LinkedIn DOM")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional DOM metadata (posted time, applicants, workplace type)")


class LinkedInJobIngestResponse(BaseModel):
    """Response returned after ingesting a LinkedIn job via extension."""
    job_id: str = Field(..., description="Job application ID")
    is_duplicate: bool = Field(False, description="Whether this job posting was already ingested previously")
    message: str = Field(..., description="Summary status message")
    job: JobResponse = Field(..., description="Persisted structured job application")
    match_analysis: Optional[JobMatchAnalysisResponse] = Field(None, description="Auto-computed evidence-backed match analysis if active resume exists")


class LinkedInQuickCaptureRequest(BaseModel):
    """Payload received from the LinkedIn Browser Extension for arbitrary, unstructured posts/pages."""
    page_url: str = Field(..., description="URL of the LinkedIn page or post (e.g. https://www.linkedin.com/posts/...)")
    page_title: Optional[str] = Field(None, description="Title of the page or post headline if detected")
    author_name: Optional[str] = Field(None, description="Name of the poster/author if detected")
    raw_text: str = Field(..., min_length=50, description="Full raw visible text content of the post or page (minimum 50 chars)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context (selection, timestamp, etc.)")


class LinkedInQuickCaptureResponse(BaseModel):
    """Response returned after staging an unstructured quick capture item."""
    id: str = Field(..., description="Staged job application ID")
    job_id: str = Field(..., description="Alias for job application ID")
    job_url: str = Field(..., description="Source page URL")
    job_title: Optional[str] = Field(None, description="Temporary draft title")
    company_name: Optional[str] = Field(None, description="Temporary author/poster name")
    raw_jd_text: str = Field(..., description="Captured raw text staged for manual review")
    status: str = Field("pending_manual_review", description="Pending review status")
    pending_review: bool = Field(True, description="Whether this item is pending manual review")
    source: str = Field("extension_quick_capture", description="Provenance marker")
    created_at: datetime = Field(..., description="Staging timestamp")
    message: str = Field(
        "Quick capture staged successfully for manual review. Open your Job Agent dashboard to review and finalize.",
        description="User feedback message"
    )

