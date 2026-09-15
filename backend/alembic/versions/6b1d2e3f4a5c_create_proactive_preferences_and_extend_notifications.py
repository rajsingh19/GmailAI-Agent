"""create_proactive_preferences_and_extend_notifications

Revision ID: 6b1d2e3f4a5c
Revises: 5a9c8e1f2b3d
Create Date: 2026-09-15 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b1d2e3f4a5c'
down_revision: Union[str, Sequence[str], None] = '5a9c8e1f2b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create user_preferences table and extend notifications table with proactive assistant fields."""
    # 1. Create user_preferences table
    op.create_table(
        'user_preferences',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('proactive_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('calendar_alerts_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('task_alerts_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('reminder_alerts_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('email_alerts_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('quiet_hours_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('quiet_hours_start', sa.String(length=5), nullable=False, server_default='22:00'),
        sa.Column('quiet_hours_end', sa.String(length=5), nullable=False, server_default='08:00'),
        sa.Column('defer_high_priority_in_quiet_hours', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('user_timezone', sa.String(length=50), nullable=False, server_default='UTC'),
        sa.Column('min_priority', sa.String(length=20), nullable=False, server_default='low'),
        sa.Column('max_proactive_per_day', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('last_gmail_proactive_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_user_preferences_user_id'), 'user_preferences', ['user_id'], unique=False)

    # 2. Extend notifications table
    op.add_column('notifications', sa.Column('notification_type', sa.String(length=50), nullable=False, server_default='reminder'))
    op.add_column('notifications', sa.Column('priority', sa.String(length=20), nullable=False, server_default='medium'))
    op.add_column('notifications', sa.Column('source_type', sa.String(length=32), nullable=True))
    op.add_column('notifications', sa.Column('source_id', sa.String(length=255), nullable=True))
    op.add_column('notifications', sa.Column('metadata_json', sa.JSON(), nullable=True))
    op.add_column('notifications', sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notifications', sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True))

    op.create_index(op.f('ix_notifications_notification_type'), 'notifications', ['notification_type'], unique=False)
    op.create_index(op.f('ix_notifications_priority'), 'notifications', ['priority'], unique=False)
    op.create_index(op.f('ix_notifications_source_type'), 'notifications', ['source_type'], unique=False)
    op.create_index(op.f('ix_notifications_source_id'), 'notifications', ['source_id'], unique=False)
    op.create_index('idx_notif_user_type', 'notifications', ['user_id', 'notification_type'], unique=False)
    op.create_index('idx_notif_user_priority', 'notifications', ['user_id', 'priority'], unique=False)

    # 3. Replace single-column unique index with user-scoped unique constraint
    op.drop_index('ix_notifications_idempotency_key', table_name='notifications')
    op.create_index(op.f('ix_notifications_idempotency_key'), 'notifications', ['idempotency_key'], unique=False)
    op.create_unique_constraint('uq_notification_user_idempotency', 'notifications', ['user_id', 'idempotency_key'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_notification_user_idempotency', 'notifications', type_='unique')
    op.drop_index(op.f('ix_notifications_idempotency_key'), table_name='notifications')
    op.create_index(op.f('ix_notifications_idempotency_key'), 'notifications', ['idempotency_key'], unique=True)


    op.drop_index('idx_notif_user_priority', table_name='notifications')
    op.drop_index('idx_notif_user_type', table_name='notifications')
    op.drop_index(op.f('ix_notifications_source_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_source_type'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_priority'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_notification_type'), table_name='notifications')

    op.drop_column('notifications', 'snoozed_until')
    op.drop_column('notifications', 'dismissed_at')
    op.drop_column('notifications', 'metadata_json')
    op.drop_column('notifications', 'source_id')
    op.drop_column('notifications', 'source_type')
    op.drop_column('notifications', 'priority')
    op.drop_column('notifications', 'notification_type')

    op.drop_index(op.f('ix_user_preferences_user_id'), table_name='user_preferences')
    op.drop_table('user_preferences')
