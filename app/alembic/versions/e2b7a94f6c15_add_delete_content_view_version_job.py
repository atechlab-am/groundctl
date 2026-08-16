"""add delete content view version job type, target type, audit actions,
all_snapshot_names column

Revision ID: e2b7a94f6c15
Revises: d1f6b83c2a94
Create Date: 2026-08-17 08:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2b7a94f6c15'
down_revision: Union[str, Sequence[str], None] = 'd1f6b83c2a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('content_view_versions', sa.Column('all_snapshot_names', sa.JSON(), nullable=True))
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'delete_content_view_version'")
        op.execute("ALTER TYPE job_target_type ADD VALUE IF NOT EXISTS 'content_view'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'trigger_delete_content_view_version'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'delete_content_view_version'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_view_versions', 'all_snapshot_names')
    # No downgrade path for an added enum value — same posture as every
    # prior enum-value migration here.
    pass
