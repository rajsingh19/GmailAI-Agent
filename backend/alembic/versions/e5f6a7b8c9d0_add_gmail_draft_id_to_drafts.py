"""add_gmail_draft_id_to_drafts

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-25 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add gmail_draft_id column to gmail_reply_drafts table."""
    op.add_column('gmail_reply_drafts', sa.Column('gmail_draft_id', sa.String(length=255), nullable=True))
    op.create_index('ix_gmail_reply_drafts_gmail_draft_id', 'gmail_reply_drafts', ['gmail_draft_id'], unique=False)


def downgrade() -> None:
    """Remove gmail_draft_id column from gmail_reply_drafts table."""
    op.drop_index('ix_gmail_reply_drafts_gmail_draft_id', table_name='gmail_reply_drafts')
    op.drop_column('gmail_reply_drafts', 'gmail_draft_id')
