"""create_user_memories_table

Revision ID: 7c2e3f4a5b6d
Revises: 6b1d2e3f4a5c
Create Date: 2026-09-16 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2e3f4a5b6d'
down_revision: Union[str, Sequence[str], None] = '6b1d2e3f4a5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create user_memories table and extend user_preferences with memory_enabled toggle."""
    # 1. Add memory_enabled column to user_preferences (Default: False for privacy-first opt-in)
    op.add_column('user_preferences', sa.Column('memory_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))

    # 2. Create user_memories table
    op.create_table(
        'user_memories',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('confidence', sa.String(length=20), nullable=False, server_default='EXPLICIT'),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='explicit_user_request'),
        sa.Column('source_reference', sa.String(length=255), nullable=True),
        sa.Column('explicitly_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_confirmed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('memory_metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'category', 'key', name='uq_user_memory_category_key')
    )
    op.create_index(op.f('ix_user_memories_id'), 'user_memories', ['id'], unique=False)
    op.create_index(op.f('ix_user_memories_user_id'), 'user_memories', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_memories_category'), 'user_memories', ['category'], unique=False)
    op.create_index(op.f('ix_user_memories_key'), 'user_memories', ['key'], unique=False)
    op.create_index(op.f('ix_user_memories_active'), 'user_memories', ['active'], unique=False)
    op.create_index('idx_user_memory_lookup', 'user_memories', ['user_id', 'active', 'category'])
    op.create_index('idx_user_memory_key', 'user_memories', ['user_id', 'key'])


def downgrade() -> None:
    """Revert user_memories table and memory_enabled column."""
    op.drop_index('idx_user_memory_key', table_name='user_memories')
    op.drop_index('idx_user_memory_lookup', table_name='user_memories')
    op.drop_index(op.f('ix_user_memories_active'), table_name='user_memories')
    op.drop_index(op.f('ix_user_memories_key'), table_name='user_memories')
    op.drop_index(op.f('ix_user_memories_category'), table_name='user_memories')
    op.drop_index(op.f('ix_user_memories_user_id'), table_name='user_memories')
    op.drop_index(op.f('ix_user_memories_id'), table_name='user_memories')
    op.drop_table('user_memories')
    op.drop_column('user_preferences', 'memory_enabled')
