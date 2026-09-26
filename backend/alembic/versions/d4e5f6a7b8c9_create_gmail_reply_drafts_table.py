"""create_gmail_reply_drafts_table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-25 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create gmail_reply_drafts table with user isolation and unique (user_id, message_id) constraint."""
    op.create_table(
        'gmail_reply_drafts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=False),
        sa.Column('thread_id', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('recipient', sa.String(length=500), nullable=True),
        sa.Column('reply_body', sa.Text(), nullable=False),
        sa.Column('tone', sa.String(length=50), nullable=False, server_default='professional'),
        sa.Column('custom_instructions', sa.Text(), nullable=True),
        sa.Column('placeholders', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'message_id', name='uq_user_gmail_reply_draft'),
    )
    op.create_index('ix_gmail_reply_drafts_id', 'gmail_reply_drafts', ['id'], unique=False)
    op.create_index('ix_gmail_reply_drafts_user_id', 'gmail_reply_drafts', ['user_id'], unique=False)
    op.create_index('ix_gmail_reply_drafts_message_id', 'gmail_reply_drafts', ['message_id'], unique=False)
    op.create_index('ix_gmail_reply_drafts_thread_id', 'gmail_reply_drafts', ['thread_id'], unique=False)
    op.create_index('ix_gmail_reply_drafts_user_message', 'gmail_reply_drafts', ['user_id', 'message_id'], unique=False)


def downgrade() -> None:
    """Drop gmail_reply_drafts table."""
    op.drop_index('ix_gmail_reply_drafts_user_message', table_name='gmail_reply_drafts')
    op.drop_index('ix_gmail_reply_drafts_thread_id', table_name='gmail_reply_drafts')
    op.drop_index('ix_gmail_reply_drafts_message_id', table_name='gmail_reply_drafts')
    op.drop_index('ix_gmail_reply_drafts_user_id', table_name='gmail_reply_drafts')
    op.drop_index('ix_gmail_reply_drafts_id', table_name='gmail_reply_drafts')
    op.drop_table('gmail_reply_drafts')
