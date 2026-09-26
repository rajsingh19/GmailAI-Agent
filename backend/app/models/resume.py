"""
User Resume model for secure resume storage, parsing, and structured profile extraction (Milestone 1).
Enforces multi-user isolation, private encrypted file tracking, and structured resume parsing.
"""
import uuid
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.core.security import EncryptedText, EncryptedJSON

if TYPE_CHECKING:
    from app.models.user import User


class UserResume(Base, TimestampMixin):
    """
    Persistent representation of a candidate resume.
    Stores extracted text, structured profile sections (summary, skills, experience, education, contact),
    and pointers to on-disk encrypted original files.
    All raw text and structured data are encrypted at rest with AES-Fernet.
    """
    __tablename__ = "user_resumes"

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
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="My Resume",
    )
    file_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    file_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    file_mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    file_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    raw_text: Mapped[str] = mapped_column(
        EncryptedText,
        nullable=False,
        default="",
    )
    structured_data: Mapped[Dict[str, Any]] = mapped_column(
        EncryptedJSON,
        nullable=False,
        default=dict,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="resumes", lazy="selectin")

    __table_args__ = (
        Index("idx_resumes_user_default", "user_id", "is_default"),
        Index("idx_resumes_user_created", "user_id", "created_at"),
    )
