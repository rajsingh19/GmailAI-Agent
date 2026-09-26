"""
Pydantic Schemas for Job Description Ingestion and Processing (Milestone 2).
Provides input validation and response serialization.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, model_validator


class JobResolveUrlRequest(BaseModel):
    """Request payload to safely resolve a job posting or shortener URL."""
    url: str = Field(
        ...,
        description="Target job URL, including shortened lnkd.in links or direct URLs.",
        min_length=5,
        max_length=2048,
    )


class JobResolveUrlResponse(BaseModel):
    """Result of safe URL resolution and accessibility inspection."""
    original_url: str
    resolved_url: str
    is_accessible: bool
    requires_pasted_jd: bool
    page_title: Optional[str] = None
    raw_text: Optional[str] = None
    source: str = "linkedin"
    reason: Optional[str] = None


class JobParseRequest(BaseModel):
    """Request payload for structured job description parsing."""
    raw_text: str = Field(
        ...,
        description="Raw job description text (from web page or user paste).",
        min_length=20,
    )
    url: Optional[str] = Field(
        None,
        description="Optional source job posting URL.",
        max_length=2048,
    )
    title: Optional[str] = Field(
        None,
        description="Optional pre-filled job title.",
        max_length=255,
    )
    company: Optional[str] = Field(
        None,
        description="Optional pre-filled company name.",
        max_length=255,
    )


class JobStructuredDetails(BaseModel):
    """Structured extraction fields from a job description."""
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    experience_level: Optional[str] = None
    description_summary: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    recruiter_email: Optional[str] = None
    recruiter_name: Optional[str] = None
    application_url: Optional[str] = None


class JobParseResponse(BaseModel):
    """Response containing parsed and structured job details."""
    raw_text: str
    source_url: Optional[str] = None
    structured_jd: JobStructuredDetails


class JobCreateRequest(BaseModel):
    """Request to persist an ingested job posting."""
    job_url: Optional[str] = Field(None, max_length=2048)
    resolved_url: Optional[str] = Field(None, max_length=2048)
    job_title: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    raw_jd_text: str = Field(..., min_length=20)
    resume_id: Optional[str] = Field(None, max_length=36)
    source: str = Field("linkedin", max_length=50)
    pending_capture_id: Optional[str] = Field(None, max_length=36, description="Optional pending quick capture ID to convert")


class JobResponse(BaseModel):
    """Full detail of a saved job application record."""
    id: str
    user_id: str
    job_url: Optional[str] = None
    resolved_url: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    experience_level: Optional[str] = None
    raw_jd_text: str
    structured_jd: Dict[str, Any]
    recruiter_email: Optional[str] = None
    recruiter_name: Optional[str] = None
    application_url: Optional[str] = None
    source: str
    status: str
    resume_id: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    gmail_message_id: Optional[str] = None
    gmail_sync_status: str = "not_synced"
    applied_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class JobSummaryResponse(BaseModel):
    """Compact summary of a saved job application for table listings."""
    id: str
    user_id: str
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    recruiter_email: Optional[str] = None
    status: str
    source: str
    gmail_sync_status: str = "not_synced"
    has_gmail_draft: bool = False
    skills_count: int = 0
    applied_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# -----------------------------------------------------------------------------
# Milestone 3: Evidence-Backed Resume Matching & Application Email Schemas
# -----------------------------------------------------------------------------

class MatchedRequirementItem(BaseModel):
    """A job requirement supported by direct resume evidence."""
    requirement: str
    category: str = "required_skill"  # required_skill, preferred_skill, experience, education, responsibility
    evidence: str
    confidence: str = "high"


class MissingRequirementItem(BaseModel):
    """A job requirement without sufficient evidence in the resume."""
    requirement: str
    category: str = "required_skill"
    status: str = "not_found_in_resume"
    recommendation: Optional[str] = None


class JobMatchAnalysisResponse(BaseModel):
    """Evidence-based match analysis between a resume and job description."""
    job_id: str
    resume_id: str
    resume_title: str
    evidence_coverage_percentage: float
    calculation_explanation: str
    matched_requirements: List[MatchedRequirementItem] = Field(default_factory=list)
    missing_requirements: List[MissingRequirementItem] = Field(default_factory=list)
    key_strengths: List[str] = Field(default_factory=list)
    potential_concerns_or_gaps: List[str] = Field(default_factory=list)


class JobMatchRequest(BaseModel):
    """Request payload to match a job posting with a resume."""
    resume_id: Optional[str] = Field(
        None,
        description="ID of specific resume to match against. If omitted, user's default resume is used.",
    )


class JobGenerateEmailRequest(BaseModel):
    """Request payload to generate a personalized application email."""
    resume_id: Optional[str] = Field(
        None,
        description="ID of specific resume to cite. If omitted, user's default resume is used.",
    )
    tone: Optional[str] = Field(
        "professional",
        description="Tone of email: professional, confident, concise, or enthusiastic.",
    )
    user_instructions: Optional[str] = Field(
        None,
        description="Optional custom focus or guidance (e.g., 'Emphasize my cloud migration background').",
        max_length=1000,
    )


class JobEmailDraftResponse(BaseModel):
    """Personalized application email draft generated from verified resume evidence."""
    job_id: str
    resume_id: Optional[str] = None
    recipient_email: Optional[str] = None
    recipient: Optional[str] = None
    recipient_name: Optional[str] = None
    subject: str
    body: str
    placeholders: List[str] = Field(default_factory=list)
    verified_skills_referenced: List[str] = Field(default_factory=list)
    tone: str = "professional"
    status: str = "draft_local"
    gmail_draft_id: Optional[str] = None
    gmail_sync_status: str = "not_synced"

    @model_validator(mode="after")
    def sync_recipient_fields(self) -> "JobEmailDraftResponse":
        if not self.recipient and self.recipient_email:
            self.recipient = self.recipient_email
        elif not self.recipient_email and self.recipient:
            self.recipient_email = self.recipient
        return self


class JobUpdateEmailDraftRequest(BaseModel):
    """Request payload to update the editable application email draft."""
    recipient_email: Optional[str] = Field(None, max_length=255)
    recipient: Optional[str] = Field(None, max_length=255)
    recipient_name: Optional[str] = Field(None, max_length=255)
    subject: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = Field(None, min_length=10)

    @model_validator(mode="after")
    def sync_recipient_fields(self) -> "JobUpdateEmailDraftRequest":
        if not self.recipient and self.recipient_email:
            self.recipient = self.recipient_email
        elif not self.recipient_email and self.recipient:
            self.recipient_email = self.recipient
        return self


# -----------------------------------------------------------------------------
# Milestone 4: Gmail Draft Integration & Lifecycle Tracking Schemas
# -----------------------------------------------------------------------------

class JobSaveGmailDraftRequest(BaseModel):
    """Request payload to save or update an application email in Gmail Drafts."""
    resume_id: Optional[str] = Field(
        None,
        description="Optional resume ID to attach. Defaults to linked or default resume.",
    )
    recipient_email: Optional[str] = Field(
        None,
        description="Optional recipient email override.",
        max_length=255,
    )
    subject: Optional[str] = Field(
        None,
        description="Optional subject override.",
        max_length=500,
    )
    body: Optional[str] = Field(
        None,
        description="Optional body override.",
        min_length=10,
    )
    attach_resume: bool = Field(
        True,
        description="Whether to decrypt and attach the user's resume (PDF/DOCX) to the Gmail draft.",
    )


class JobSaveGmailDraftResponse(BaseModel):
    """Result of saving an application email directly into the user's Gmail Drafts."""
    job_id: str
    gmail_draft_id: str
    gmail_message_id: Optional[str] = None
    gmail_sync_status: str = "synced"
    status: str = "draft_saved_to_gmail"
    attachment_filename: Optional[str] = None
    attachment_size_bytes: Optional[int] = None
    gmail_web_url: str = "https://mail.google.com/mail/u/0/#drafts"
    message: str = "Application draft saved to Gmail Drafts folder."


class JobStatusUpdateRequest(BaseModel):
    """Request payload to transition job application lifecycle state."""
    status: str = Field(
        ...,
        description="Target status: saved, draft_local, draft_saved_to_gmail, applied_manually, interview, offer, rejected, archived",
    )


