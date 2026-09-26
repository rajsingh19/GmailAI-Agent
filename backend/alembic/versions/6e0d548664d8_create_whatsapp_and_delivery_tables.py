"""create_whatsapp_and_delivery_tables

Revision ID: 6e0d548664d8
Revises: 9e4f5a6b7c8d
Create Date: 2026-09-18 00:03:27.674884

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e0d548664d8'
down_revision: Union[str, Sequence[str], None] = '9e4f5a6b7c8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create whatsapp_destinations and notification_deliveries tables."""
    # 1. Create whatsapp_destinations table
    op.create_table(
        'whatsapp_destinations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('phone_number_encrypted', sa.Text(), nullable=False),
        sa.Column('phone_number_masked', sa.String(length=32), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('opt_in_confirmed', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('opt_in_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='not_configured', nullable=False),
        sa.Column('environment', sa.String(length=32), server_default='sandbox', nullable=False),
        sa.Column('last_message_sid', sa.String(length=64), nullable=True),
        sa.Column('last_delivery_status', sa.String(length=32), nullable=True),
        sa.Column('last_error', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_whatsapp_destinations_user_id'),
    )
    op.create_index('ix_whatsapp_destinations_id', 'whatsapp_destinations', ['id'], unique=False)
    op.create_index('ix_whatsapp_destinations_user_id', 'whatsapp_destinations', ['user_id'], unique=True)
    op.create_index('ix_whatsapp_destinations_status', 'whatsapp_destinations', ['status'], unique=False)

    # 2. Create notification_deliveries table
    op.create_table(
        'notification_deliveries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('notification_id', sa.String(length=36), nullable=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('channel', sa.String(length=32), server_default='whatsapp', nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('provider_message_sid', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'notification_id', 'channel', name='uq_notification_delivery_channel'),
    )
    op.create_index('ix_notification_deliveries_id', 'notification_deliveries', ['id'], unique=False)
    op.create_index('ix_notification_deliveries_notification_id', 'notification_deliveries', ['notification_id'], unique=False)
    op.create_index('ix_notification_deliveries_user_id', 'notification_deliveries', ['user_id'], unique=False)
    op.create_index('ix_notification_deliveries_channel', 'notification_deliveries', ['channel'], unique=False)
    op.create_index('ix_notification_deliveries_idempotency_key', 'notification_deliveries', ['idempotency_key'], unique=False)
    op.create_index('ix_notification_deliveries_provider_message_sid', 'notification_deliveries', ['provider_message_sid'], unique=False)
    op.create_index('ix_notification_deliveries_status', 'notification_deliveries', ['status'], unique=False)
    op.create_index('ix_notification_deliveries_next_retry_at', 'notification_deliveries', ['next_retry_at'], unique=False)
    op.create_index('ix_delivery_retry', 'notification_deliveries', ['status', 'next_retry_at'], unique=False)


def downgrade() -> None:
    """Drop notification_deliveries and whatsapp_destinations tables."""
    # Drop notification_deliveries
    op.drop_index('ix_delivery_retry', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_next_retry_at', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_status', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_provider_message_sid', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_idempotency_key', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_channel', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_user_id', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_notification_id', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_id', table_name='notification_deliveries')
    op.drop_table('notification_deliveries')

    # Drop whatsapp_destinations
    op.drop_index('ix_whatsapp_destinations_status', table_name='whatsapp_destinations')
    op.drop_index('ix_whatsapp_destinations_user_id', table_name='whatsapp_destinations')
    op.drop_index('ix_whatsapp_destinations_id', table_name='whatsapp_destinations')
    op.drop_table('whatsapp_destinations')
