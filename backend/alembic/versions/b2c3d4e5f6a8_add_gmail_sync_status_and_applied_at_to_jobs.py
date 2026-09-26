"""add_gmail_sync_status_and_applied_at_to_jobs

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-26 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add gmail_sync_status and applied_at to job_applications."""
    op.add_column(
        'job_applications',
        sa.Column('gmail_sync_status', sa.String(length=50), nullable=False, server_default='not_synced'),
    )
    op.add_column(
        'job_applications',
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_job_applications_gmail_sync_status', 'job_applications', ['gmail_sync_status'], unique=False)


def downgrade() -> None:
    """Drop gmail_sync_status and applied_at from job_applications."""
    op.drop_index('ix_job_applications_gmail_sync_status', table_name='job_applications')
    op.drop_column('job_applications', 'applied_at')
    op.drop_column('job_applications', 'gmail_sync_status')
