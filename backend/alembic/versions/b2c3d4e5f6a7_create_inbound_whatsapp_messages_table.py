"""create_inbound_whatsapp_messages_table

Revision ID: b2c3d4e5f6a7
Revises: 6e0d548664d8
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '6e0d548664d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inbound_whatsapp_messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('message_sid', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('from_number', sa.String(length=32), nullable=False),
        sa.Column('to_number', sa.String(length=32), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('num_media', sa.Integer(), server_default='0', nullable=False),
        sa.Column('raw_payload', sa.Text(), nullable=True),
        sa.Column('processed', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_sid', name='uq_inbound_whatsapp_messages_sid'),
    )
    op.create_index('ix_inbound_whatsapp_messages_id', 'inbound_whatsapp_messages', ['id'], unique=False)
    op.create_index('ix_inbound_whatsapp_messages_message_sid', 'inbound_whatsapp_messages', ['message_sid'], unique=True)
    op.create_index('ix_inbound_whatsapp_messages_user_id', 'inbound_whatsapp_messages', ['user_id'], unique=False)
    op.create_index('ix_inbound_whatsapp_messages_from_number', 'inbound_whatsapp_messages', ['from_number'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_inbound_whatsapp_messages_from_number', table_name='inbound_whatsapp_messages')
    op.drop_index('ix_inbound_whatsapp_messages_user_id', table_name='inbound_whatsapp_messages')
    op.drop_index('ix_inbound_whatsapp_messages_message_sid', table_name='inbound_whatsapp_messages')
    op.drop_index('ix_inbound_whatsapp_messages_id', table_name='inbound_whatsapp_messages')
    op.drop_table('inbound_whatsapp_messages')
