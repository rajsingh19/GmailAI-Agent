"""
Knowledge Document and Chunk models for Personal Knowledge RAG (Milestone 7).
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base, TimestampMixin


class KnowledgeDocument(Base, TimestampMixin):
    """
    Represents an ingested source document (individual Gmail message, Calendar event, Task, or Reminder).
    Enforces strict user isolation and content hashing for idempotent indexing.
    """
    __tablename__ = "knowledge_documents"

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
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )  # "gmail", "calendar", "task", "reminder"
    source_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )  # External source ID (e.g. Gmail message ID, Google Calendar event ID)
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )  # SHA-256 hex digest of normalized content
    doc_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )  # "active", "archived", "deleted"
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunk.chunk_index",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "source_type", "source_id", name="uq_knowledge_doc_user_source"),
        Index("idx_kdoc_user_status", "user_id", "status"),
    )


class KnowledgeChunk(Base):
    """
    Represents an embedded text chunk for vector similarity search.
    Retains user_id and document provenance.
    """
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    embedding: Mapped[List[float]] = mapped_column(
        Vector(768),
        nullable=False,
    )  # 768-dimensional float embedding vector
    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    chunk_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @property
    def embedding_vector(self) -> List[float]:
        if self.embedding is None:
            return []
        return list(self.embedding)

    # Relationships
    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument",
        back_populates="chunks",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_kchunk_user_id", "user_id"),
        Index("idx_kchunk_doc_id", "document_id"),
        Index("idx_kchunk_user_doc", "user_id", "document_id"),
    )
