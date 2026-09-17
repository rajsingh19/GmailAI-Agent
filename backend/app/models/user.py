import uuid
from typing import List, Optional
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """
    User entity representing an application user.
    Acts as the multi-tenant isolation root for all associated accounts, tokens, and data.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    picture_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships (cascade delete when user is deleted)
    google_accounts: Mapped[List["GoogleAccount"]] = relationship(
        "GoogleAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    oauth_tokens: Mapped[List["OAuthToken"]] = relationship(
        "OAuthToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reminders: Mapped[List["Reminder"]] = relationship(
        "Reminder",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    preferences: Mapped[Optional["UserPreference"]] = relationship(
        "UserPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    memories: Mapped[List["UserMemory"]] = relationship(
        "UserMemory",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    push_subscriptions: Mapped[List["PushSubscription"]] = relationship(
        "PushSubscription",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"

