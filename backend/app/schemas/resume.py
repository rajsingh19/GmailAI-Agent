"""
Pydantic schemas for Resume Storage and Extraction (Milestone 1).
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ResumeExperienceItem(BaseModel):
    company: Optional[str] = None
    role: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class ResumeEducationItem(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    year: Optional[str] = None


class ResumeProjectItem(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    technologies: List[str] = Field(default_factory=list)
    link: Optional[str] = None


class ResumeContactInfo(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    location: Optional[str] = None
    portfolio: Optional[str] = None


class ResumeStructuredData(BaseModel):
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    experience: List[ResumeExperienceItem] = Field(default_factory=list)
    education: List[ResumeEducationItem] = Field(default_factory=list)
    projects: List[ResumeProjectItem] = Field(default_factory=list)
    contact: ResumeContactInfo = Field(default_factory=ResumeContactInfo)


class ResumeCreateTextRequest(BaseModel):
    title: str = Field(default="My Resume", min_length=1, max_length=255)
    raw_text: str = Field(..., min_length=10, description="Raw text or markdown content of the resume")
    is_default: bool = Field(default=True)


class ResumeUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    raw_text: Optional[str] = Field(None, min_length=10)
    is_default: Optional[bool] = None


class ResumeResponse(BaseModel):
    id: str
    user_id: str
    title: str
    file_name: Optional[str] = None
    file_size_bytes: Optional[int] = None
    file_mime_type: Optional[str] = None
    file_hash: Optional[str] = None
    raw_text: str
    structured_data: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class ResumeSummaryResponse(BaseModel):
    id: str
    user_id: str
    title: str
    file_name: Optional[str] = None
    file_size_bytes: Optional[int] = None
    file_mime_type: Optional[str] = None
    is_default: bool
    skills_count: int = 0
    experience_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}
