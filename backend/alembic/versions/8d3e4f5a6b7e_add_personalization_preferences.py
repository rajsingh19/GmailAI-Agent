"""add_personalization_preferences

Revision ID: 8d3e4f5a6b7e
Revises: 7c2e3f4a5b6d
Create Date: 2026-09-16 23:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d3e4f5a6b7e'
down_revision: Union[str, Sequence[str], None] = '7c2e3f4a5b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Milestone 12 personalization fields to user_preferences table."""
    op.add_column('user_preferences', sa.Column('personalization_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('user_preferences', sa.Column('personalization_level', sa.String(length=20), nullable=False, server_default='MEDIUM'))
    op.add_column('user_preferences', sa.Column('personalize_response_style', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('user_preferences', sa.Column('personalize_project_context', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('user_preferences', sa.Column('personalize_workflow_habits', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    """Remove Milestone 12 personalization fields from user_preferences table."""
    op.drop_column('user_preferences', 'personalize_workflow_habits')
    op.drop_column('user_preferences', 'personalize_project_context')
    op.drop_column('user_preferences', 'personalize_response_style')
    op.drop_column('user_preferences', 'personalization_level')
    op.drop_column('user_preferences', 'personalization_enabled')
