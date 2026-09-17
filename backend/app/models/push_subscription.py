import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PushSubscription(Base):
    """
    Web Push Subscription entity representing a browser push capability registration.
    Each subscription is tied strictly to an authenticated user.
    Database-level uniqueness on `endpoint` ensures that a push capability cannot belong
    to multiple users simultaneously.
    """
    __tablename__ = "push_subscriptions"

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
    endpoint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
        index=True,
    )
    p256dh_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    auth_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    device_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="push_subscriptions")

    def __repr__(self) -> str:
        return f"<PushSubscription(id={self.id}, user_id={self.user_id}, device={self.device_name})>"
