import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.task import Task
    from app.models.notification import Notification


class Reminder(Base, TimestampMixin):
    """
    User-isolated reminder representation.
    Supports one-time and recurring schedules, atomic state transitions,
    and optional task association.
    """
    __tablename__ = "reminders"

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
    task_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="SET NULL"),
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
    remind_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(50),
        default="UTC",
        nullable=False,
    )
    recurrence_rule: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="scheduled",
        nullable=False,
        index=True,
    )
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_trigger_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="reminders",
    )
    task: Mapped[Optional["Task"]] = relationship(
        "Task",
        back_populates="reminders",
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="reminder",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Reminder id={self.id} user_id={self.user_id} title={self.title[:20]} status={self.status} next={self.next_trigger_at}>"
