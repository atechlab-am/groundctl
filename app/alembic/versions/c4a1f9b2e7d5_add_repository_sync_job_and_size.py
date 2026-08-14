"""add repository size_bytes, last_sync_job_id, job repository target

Revision ID: c4a1f9b2e7d5
Revises: bf3d347ed1d3
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4a1f9b2e7d5'
down_revision: Union[str, Sequence[str], None] = 'bf3d347ed1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('jobs', sa.Column('repository_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'jobs_repository_id_fkey', 'jobs', 'repositories', ['repository_id'], ['id'],
        ondelete='SET NULL',
    )

    op.add_column('repositories', sa.Column('size_bytes', sa.BigInteger(), nullable=True))
    op.add_column('repositories', sa.Column('last_sync_job_id', sa.UUID(), nullable=True))
    # use_alter: jobs.repository_id -> repositories.id already exists above,
    # so this second, opposite-direction FK must be added post-hoc rather
    # than inline on the column (mirrors models.py's use_alter=True on
    # Repository.last_sync_job_id — avoids a circular create-table
    # dependency between the two tables).
    op.create_foreign_key(
        'repositories_last_sync_job_id_fkey', 'repositories', 'jobs', ['last_sync_job_id'], ['id']
    )

    # Same autocommit_block requirement as bf3d347ed1d3's audit_action
    # values — new enum labels must commit before any row can reference them.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'sync_repository'")
        op.execute("ALTER TYPE job_target_type ADD VALUE IF NOT EXISTS 'repository'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'update_repository'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'delete_repository'")


def downgrade() -> None:
    """Downgrade schema."""
    # Same posture as bf3d347ed1d3: no downgrade path for the added enum
    # values (Postgres has no ALTER TYPE ... DROP VALUE).
    op.drop_constraint('repositories_last_sync_job_id_fkey', 'repositories', type_='foreignkey')
    op.drop_column('repositories', 'last_sync_job_id')
    op.drop_column('repositories', 'size_bytes')
    op.drop_constraint('jobs_repository_id_fkey', 'jobs', type_='foreignkey')
    op.drop_column('jobs', 'repository_id')
