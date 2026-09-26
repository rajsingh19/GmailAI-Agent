"""create_job_applications_and_encrypt_resumes

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-09-26 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    1. Alter user_resumes.structured_data from JSON to Text for encrypted-at-rest storage.
    2. Create job_applications table with encrypted-at-rest fields for Milestone 2.
    """
    # Alter user_resumes.structured_data to Text
    op.alter_column(
        'user_resumes',
        'structured_data',
        existing_type=sa.JSON(),
        type_=sa.Text(),
        postgresql_using='structured_data::text',
        existing_nullable=False,
        server_default='',
    )

    # Create job_applications table
    op.create_table(
        'job_applications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('job_url', sa.String(length=2048), nullable=True),
        sa.Column('resolved_url', sa.String(length=2048), nullable=True),
        sa.Column('job_title', sa.String(length=255), nullable=True),
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('job_type', sa.String(length=50), nullable=True),
        sa.Column('experience_level', sa.String(length=50), nullable=True),
        sa.Column('raw_jd_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('structured_jd', sa.Text(), nullable=False, server_default=''),
        sa.Column('recruiter_email', sa.String(length=255), nullable=True),
        sa.Column('recruiter_name', sa.String(length=255), nullable=True),
        sa.Column('application_url', sa.String(length=2048), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='linkedin'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='saved'),
        sa.Column('resume_id', sa.String(length=36), nullable=True),
        sa.Column('match_analysis', sa.Text(), nullable=False, server_default=''),
        sa.Column('generated_email_draft', sa.Text(), nullable=False, server_default=''),
        sa.Column('gmail_draft_id', sa.String(length=255), nullable=True),
        sa.Column('gmail_message_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resume_id'], ['user_resumes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_job_applications_id', 'job_applications', ['id'], unique=False)
    op.create_index('ix_job_applications_user_id', 'job_applications', ['user_id'], unique=False)
    op.create_index('ix_job_applications_job_title', 'job_applications', ['job_title'], unique=False)
    op.create_index('ix_job_applications_company_name', 'job_applications', ['company_name'], unique=False)
    op.create_index('ix_job_applications_recruiter_email', 'job_applications', ['recruiter_email'], unique=False)
    op.create_index('ix_job_applications_status', 'job_applications', ['status'], unique=False)
    op.create_index('ix_job_applications_resume_id', 'job_applications', ['resume_id'], unique=False)
    op.create_index('idx_jobs_user_status', 'job_applications', ['user_id', 'status'], unique=False)
    op.create_index('idx_jobs_user_created', 'job_applications', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Revert job_applications table and revert user_resumes.structured_data."""
    op.drop_index('idx_jobs_user_created', table_name='job_applications')
    op.drop_index('idx_jobs_user_status', table_name='job_applications')
    op.drop_index('ix_job_applications_resume_id', table_name='job_applications')
    op.drop_index('ix_job_applications_status', table_name='job_applications')
    op.drop_index('ix_job_applications_recruiter_email', table_name='job_applications')
    op.drop_index('ix_job_applications_company_name', table_name='job_applications')
    op.drop_index('ix_job_applications_job_title', table_name='job_applications')
    op.drop_index('ix_job_applications_user_id', table_name='job_applications')
    op.drop_index('ix_job_applications_id', table_name='job_applications')
    op.drop_table('job_applications')

    op.alter_column(
        'user_resumes',
        'structured_data',
        existing_type=sa.Text(),
        type_=sa.JSON(),
        postgresql_using='structured_data::json',
        existing_nullable=False,
        server_default='{}',
    )
