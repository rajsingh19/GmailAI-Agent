"""drop_whatsapp_tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop inbound_whatsapp_messages, notification_deliveries, and whatsapp_destinations tables."""
    # 1. Drop inbound_whatsapp_messages
    op.drop_index('ix_inbound_whatsapp_messages_from_number', table_name='inbound_whatsapp_messages', if_exists=True)
    op.drop_index('ix_inbound_whatsapp_messages_user_id', table_name='inbound_whatsapp_messages', if_exists=True)
    op.drop_index('ix_inbound_whatsapp_messages_message_sid', table_name='inbound_whatsapp_messages', if_exists=True)
    op.drop_index('ix_inbound_whatsapp_messages_id', table_name='inbound_whatsapp_messages', if_exists=True)
    op.drop_table('inbound_whatsapp_messages', if_exists=True)

    # 2. Drop notification_deliveries
    op.drop_index('ix_delivery_retry', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_next_retry_at', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_status', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_provider_message_sid', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_idempotency_key', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_channel', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_user_id', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_notification_id', table_name='notification_deliveries', if_exists=True)
    op.drop_index('ix_notification_deliveries_id', table_name='notification_deliveries', if_exists=True)
    op.drop_table('notification_deliveries', if_exists=True)

    # 3. Drop whatsapp_destinations
    op.drop_index('ix_whatsapp_destinations_status', table_name='whatsapp_destinations', if_exists=True)
    op.drop_index('ix_whatsapp_destinations_user_id', table_name='whatsapp_destinations', if_exists=True)
    op.drop_index('ix_whatsapp_destinations_id', table_name='whatsapp_destinations', if_exists=True)
    op.drop_table('whatsapp_destinations', if_exists=True)


def downgrade() -> None:
    """No-op downgrade for dropped WhatsApp tables."""
    pass
