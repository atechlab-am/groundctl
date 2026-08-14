"""add delete_content_view and delete_content_view_filter audit actions

Revision ID: a3d8e26f5c91
Revises: f7c3b19d4e02
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3d8e26f5c91'
down_revision: Union[str, Sequence[str], None] = 'f7c3b19d4e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same autocommit_block pattern as every prior enum-value addition
    # here (e.g. e7a3c15f9b2d, f7c3b19d4e02) — must commit before any row
    # can reference it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'delete_content_view'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'delete_content_view_filter'")


def downgrade() -> None:
    """Downgrade schema."""
    # No downgrade path for an added enum value (Postgres has no ALTER TYPE
    # ... DROP VALUE) — same posture as every prior enum-value migration here.
    pass
