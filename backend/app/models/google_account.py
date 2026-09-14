import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class GoogleAccount(Base, TimestampMixin):
    """
    Connected Google Account representation.
    Strictly isolated per user via user_id foreign key.
    """
    __tablename__ = "google_accounts"

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
    google_user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    picture_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="google_accounts",
    )
    oauth_tokens: Mapped[List["OAuthToken"]] = relationship(
        "OAuthToken",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<GoogleAccount id={self.id} email={self.email} user_id={self.user_id}>"


class OAuthToken(Base, TimestampMixin):
    """
    Encrypted OAuth 2.0 access and refresh tokens.
    Guarantees user isolation with both user_id and account_id foreign keys.
    Tokens are ALWAYS encrypted at rest using AES-128-CBC / Fernet.
    """
    __tablename__ = "oauth_tokens"

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
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("google_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encrypted_access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    encrypted_refresh_token: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    token_type: Mapped[str] = mapped_column(
        String(50),
        default="Bearer",
        nullable=False,
    )
    scopes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="oauth_tokens",
    )
    account: Mapped["GoogleAccount"] = relationship(
        "GoogleAccount",
        back_populates="oauth_tokens",
    )

    def __repr__(self) -> str:
        return f"<OAuthToken id={self.id} user_id={self.user_id} account_id={self.account_id}>"
