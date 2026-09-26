"""
Gmail Reply Draft database model.
Provides persistent, user-isolated cloud storage for Smart Reply drafts.
Enables cross-device synchronization (mobile, desktop, multiple browsers, restarts)
without saving drafts to or modifying the user's Gmail mailbox.
"""
import uuid
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import (
    String,
    Text,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class GmailReplyDraft(Base, TimestampMixin):
    """
    Persistent representation of an on-demand generated or edited email reply draft.
    Guarantees multi-user isolation, cross-device persistence, and atomic upserts per email.
    """
    __tablename__ = "gmail_reply_drafts"

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
    message_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    gmail_draft_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    subject: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    recipient: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    reply_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    tone: Mapped[str] = mapped_column(
        String(50),
        default="professional",
        nullable=False,
    )
    custom_instructions: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    placeholders: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="gmail_reply_drafts",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_user_gmail_reply_draft"),
        Index("ix_gmail_reply_drafts_user_message", "user_id", "message_id"),
    )

    def __repr__(self) -> str:
        return f"<GmailReplyDraft id={self.id} user_id={self.user_id} message_id={self.message_id}>"
