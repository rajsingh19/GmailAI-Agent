import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.reminder import Reminder


class Task(Base, TimestampMixin):
    """
    User-isolated task representation.
    Tracks priority, status (pending, completed, cancelled), and due dates.
    """
    __tablename__ = "tasks"

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
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(50),
        default="medium",
        nullable=False,
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    timezone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="UTC",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="tasks",
    )
    reminders: Mapped[List["Reminder"]] = relationship(
        "Reminder",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} user_id={self.user_id} title={self.title[:20]} status={self.status}>"
