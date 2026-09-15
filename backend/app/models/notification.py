import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.reminder import Reminder


class Notification(Base):
    """
    In-app notification event created when a reminder triggers.
    Includes idempotency_key with unique constraint to prevent duplicate delivery.
    """
    __tablename__ = "notifications"

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
    reminder_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("reminders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="unread",
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="notifications",
    )
    reminder: Mapped[Optional["Reminder"]] = relationship(
        "Reminder",
        back_populates="notifications",
    )

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user_id={self.user_id} title={self.title[:20]} status={self.status}>"
