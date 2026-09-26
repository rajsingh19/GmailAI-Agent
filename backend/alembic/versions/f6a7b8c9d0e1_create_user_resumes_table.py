"""create_user_resumes_table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-26 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create user_resumes table for Milestone 1 secure resume storage."""
    op.create_table(
        'user_resumes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, server_default='My Resume'),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('file_mime_type', sa.String(length=100), nullable=True),
        sa.Column('file_hash', sa.String(length=64), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('structured_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_resumes_id', 'user_resumes', ['id'], unique=False)
    op.create_index('ix_user_resumes_user_id', 'user_resumes', ['user_id'], unique=False)
    op.create_index('ix_user_resumes_file_hash', 'user_resumes', ['file_hash'], unique=False)
    op.create_index('ix_user_resumes_is_default', 'user_resumes', ['is_default'], unique=False)
    op.create_index('idx_resumes_user_default', 'user_resumes', ['user_id', 'is_default'], unique=False)
    op.create_index('idx_resumes_user_created', 'user_resumes', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Drop user_resumes table."""
    op.drop_index('idx_resumes_user_created', table_name='user_resumes')
    op.drop_index('idx_resumes_user_default', table_name='user_resumes')
    op.drop_index('ix_user_resumes_is_default', table_name='user_resumes')
    op.drop_index('ix_user_resumes_file_hash', table_name='user_resumes')
    op.drop_index('ix_user_resumes_user_id', table_name='user_resumes')
    op.drop_index('ix_user_resumes_id', table_name='user_resumes')
    op.drop_table('user_resumes')
