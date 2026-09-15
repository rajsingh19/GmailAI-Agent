import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.reminder import Reminder


class Notification(Base):
    """
    In-app notification entity.
    Supports reminder alerts, proactive assistant alerts, schedule conflicts, and task suggestions.
    Guarantees user-scoped idempotency via composite unique constraint (user_id, idempotency_key).
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
        nullable=False,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(
        String(50),
        default="reminder",
        nullable=False,
        index=True,
    )  # "reminder", "meeting_soon", "calendar_conflict", "dense_schedule", "task_overdue", "task_due_soon", "email_actionable", "meeting_prep", "daily_briefing"
    priority: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
        index=True,
    )  # "low", "medium", "high", "urgent"
    source_type: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )  # "reminder", "task", "calendar", "gmail", "system"
    source_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
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
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
    )  # Stores SuggestedAction, citations, event timestamps, detector metadata
    status: Mapped[str] = mapped_column(
        String(50),
        default="unread",
        nullable=False,
        index=True,
    )  # "unread", "read", "dismissed", "snoozed"
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
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(
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

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_notification_user_idempotency"),
        Index("idx_notif_user_status", "user_id", "status"),
        Index("idx_notif_user_type", "user_id", "notification_type"),
        Index("idx_notif_user_priority", "user_id", "priority"),
    )

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user_id={self.user_id} type={self.notification_type} priority={self.priority} status={self.status}>"
