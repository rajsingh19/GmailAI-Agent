"""create_push_subscriptions_table

Revision ID: 9e4f5a6b7c8d
Revises: 8d3e4f5a6b7e
Create Date: 2026-09-17 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e4f5a6b7c8d'
down_revision: Union[str, Sequence[str], None] = '8d3e4f5a6b7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create push_subscriptions table with unique endpoint constraint."""
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh_key', sa.String(length=255), nullable=False),
        sa.Column('auth_key', sa.String(length=255), nullable=False),
        sa.Column('device_name', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint', name='uq_push_subscriptions_endpoint'),
    )
    op.create_index('ix_push_subscriptions_id', 'push_subscriptions', ['id'], unique=False)
    op.create_index('ix_push_subscriptions_user_id', 'push_subscriptions', ['user_id'], unique=False)


def downgrade() -> None:
    """Drop push_subscriptions table."""
    op.drop_index('ix_push_subscriptions_user_id', table_name='push_subscriptions')
    op.drop_index('ix_push_subscriptions_id', table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
