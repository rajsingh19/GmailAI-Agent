"""
User Memory model for Long-Term Personal Memory & Personalization (Milestone 11).
Enforces strict multi-user isolation, provenance tracking, deterministic confidence scoring,
and unique category-key constraints for conflict resolution.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import (
    String,
    Text,
    Boolean,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserMemory(Base, TimestampMixin):
    """
    Structured personal memory and persistent preferences.
    Guarantees user isolation, auditable provenance, confidence scoring,
    and soft deactivation for agent personalization.
    """
    __tablename__ = "user_memories"

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
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # "user_preference", "user_fact", "project_context", "workflow_preference", "explicit_user_memory"

    key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )  # Normalized lookup key e.g. "coding.preferred_language", "project.primary_framework"

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )  # The stored memory / preference value (max 2,000 chars)

    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )  # Human-readable explanation or context

    confidence: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="EXPLICIT",
    )  # "EXPLICIT", "HIGH_CONFIDENCE", "MEDIUM_CONFIDENCE", "LOW_CONFIDENCE"

    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
    )  # Normalized score: EXPLICIT=1.0, HIGH=0.85, MEDIUM=0.65, LOW=0.40

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="explicit_user_request",
    )  # "explicit_user_request", "agent_inference", "user_ui"

    source_reference: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )  # Optional conversation / execution ID reference

    explicitly_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,  # Set True ONLY on explicit user creation or confirmation
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    memory_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="memories", lazy="joined")

    __table_args__ = (
        UniqueConstraint("user_id", "category", "key", name="uq_user_memory_category_key"),
        Index("idx_user_memory_lookup", "user_id", "active", "category"),
        Index("idx_user_memory_key", "user_id", "key"),
    )

    def __repr__(self) -> str:
        return f"<UserMemory id={self.id} user_id={self.user_id} category={self.category} key={self.key} active={self.active}>"
