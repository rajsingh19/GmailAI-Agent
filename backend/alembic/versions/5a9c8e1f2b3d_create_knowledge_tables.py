"""create_knowledge_tables

Revision ID: 5a9c8e1f2b3d
Revises: 3e8b2d9d7e6f
Create Date: 2026-09-15 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '5a9c8e1f2b3d'
down_revision: Union[str, Sequence[str], None] = '3e8b2d9d7e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to include knowledge_documents and knowledge_chunks."""
    # Attempt to create pgvector extension if running on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 1. Create knowledge_documents
    op.create_table(
        'knowledge_documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('source_id', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('doc_metadata', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'source_type', 'source_id', name='uq_knowledge_doc_user_source')
    )
    op.create_index(op.f('ix_knowledge_documents_id'), 'knowledge_documents', ['id'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_user_id'), 'knowledge_documents', ['user_id'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_source_type'), 'knowledge_documents', ['source_type'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_source_id'), 'knowledge_documents', ['source_id'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_content_hash'), 'knowledge_documents', ['content_hash'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_status'), 'knowledge_documents', ['status'], unique=False)
    op.create_index('idx_kdoc_user_status', 'knowledge_documents', ['user_id', 'status'], unique=False)

    # 2. Create knowledge_chunks with Vector(768)
    op.create_table(
        'knowledge_chunks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(768), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('chunk_metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_chunks_id'), 'knowledge_chunks', ['id'], unique=False)
    op.create_index(op.f('ix_knowledge_chunks_document_id'), 'knowledge_chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_knowledge_chunks_user_id'), 'knowledge_chunks', ['user_id'], unique=False)
    op.create_index('idx_kchunk_user_id', 'knowledge_chunks', ['user_id'], unique=False)
    op.create_index('idx_kchunk_doc_id', 'knowledge_chunks', ['document_id'], unique=False)
    op.create_index('idx_kchunk_user_doc', 'knowledge_chunks', ['user_id', 'document_id'], unique=False)

    # 3. Create HNSW index on PostgreSQL for fast vector cosine similarity search
    if bind.dialect.name == "postgresql":
        op.execute("CREATE INDEX IF NOT EXISTS idx_kchunk_hnsw_cosine ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_kchunk_hnsw_cosine;")
    op.drop_table('knowledge_chunks')
    op.drop_table('knowledge_documents')

