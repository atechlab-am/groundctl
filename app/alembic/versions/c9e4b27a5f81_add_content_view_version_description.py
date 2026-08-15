"""add content view version description

Revision ID: c9e4b27a5f81
Revises: a7c3e91f4b28
Create Date: 2026-08-16 06:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e4b27a5f81'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91f4b28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('content_view_versions', sa.Column('description', sa.Text(), nullable=True))
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'update_content_view_version'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_view_versions', 'description')
