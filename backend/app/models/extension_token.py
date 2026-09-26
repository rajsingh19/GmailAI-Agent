"""
Extension Token Model for LinkedIn Job Capture Extension.
Provides distinct, revocable, and auditable credentials separate from web session JWTs.
Stores only SHA-256 hash of tokens server-side.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class ExtensionToken(Base, TimestampMixin):
    """
    Dedicated API credential for the LinkedIn Browser Extension.
    Only the SHA-256 hash is persisted server-side.
    """
    __tablename__ = "extension_tokens"

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
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    token_prefix: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="LinkedIn Browser Extension",
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", lazy="selectin", back_populates="extension_tokens")

    __table_args__ = (
        Index("idx_ext_token_user_active", "user_id", "revoked_at"),
    )

    @property
    def is_active(self) -> bool:
        """Returns True if the token is not revoked."""
        return self.revoked_at is None
