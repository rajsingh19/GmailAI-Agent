"""
User Preferences model for Proactive Assistant & System Configuration (Milestone 8).
Enforces privacy-first opt-in default, granular category controls, and quiet hours.
"""
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserPreference(Base, TimestampMixin):
    """
    User-specific preferences for the Proactive AI Assistant.
    Privacy-conscious default: proactive_enabled is False until explicitly enabled by the user.
    """
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    # Proactive Monitoring Master Toggle (Opt-in Default: False)
    proactive_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    # Category Toggles
    calendar_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    task_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    reminder_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    email_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Quiet Hours Settings
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    quiet_hours_start: Mapped[str] = mapped_column(
        String(5),
        default="22:00",
        nullable=False,
    )  # HH:MM format
    quiet_hours_end: Mapped[str] = mapped_column(
        String(5),
        default="08:00",
        nullable=False,
    )  # HH:MM format
    defer_high_priority_in_quiet_hours: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Timezone and Priority Thresholds
    user_timezone: Mapped[str] = mapped_column(
        String(50),
        default="UTC",
        nullable=False,
    )
    min_priority: Mapped[str] = mapped_column(
        String(20),
        default="low",
        nullable=False,
    )  # "low", "medium", "high", "urgent"

    # Rate Limiting & Cooldown Controls
    max_proactive_per_day: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )

    # Lightweight Gmail State Checkpoint Cursor
    last_gmail_proactive_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationship
    user: Mapped["User"] = relationship(
        "User",
        back_populates="preferences",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<UserPreference user_id={self.user_id} proactive_enabled={self.proactive_enabled}>"
