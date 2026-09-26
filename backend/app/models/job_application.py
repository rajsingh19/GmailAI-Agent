"""
Job Application model for LinkedIn Job URL & Ingestion Agent.
Enforces multi-user isolation, private encrypted JD storage at rest,
and tracking across saved, drafted, and applied states.
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.core.security import EncryptedText, EncryptedJSON

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.resume import UserResume


class JobApplication(Base, TimestampMixin):
    """
    Persistent representation of a job posting and application workflow.
    Stores raw JD text, structured extraction fields, and lifecycle state.
    Raw JD and structured details are encrypted at rest with AES-Fernet.
    """
    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
    )
    resolved_url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
    )
    job_title: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    company_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    job_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    experience_level: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    raw_jd_text: Mapped[str] = mapped_column(
        EncryptedText,
        nullable=False,
        default="",
    )
    structured_jd: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON,
        nullable=False,
        default=dict,
    )
    recruiter_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    recruiter_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    application_url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="linkedin",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="saved",
        index=True,
    )
    resume_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("user_resumes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    match_analysis: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON,
        nullable=False,
        default=dict,
    )
    generated_email_draft: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON,
        nullable=False,
        default=dict,
    )
    gmail_draft_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    gmail_message_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    gmail_sync_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="not_synced",
        index=True,
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", lazy="selectin")
    resume: Mapped[Optional["UserResume"]] = relationship("UserResume", lazy="selectin")

    __table_args__ = (
        Index("idx_jobs_user_status", "user_id", "status"),
        Index("idx_jobs_user_created", "user_id", "created_at"),
    )
