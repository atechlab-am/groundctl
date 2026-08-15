"""add install_beacon job type and audit action

Revision ID: a7c3e91f4b28
Revises: f2d9a4c8b613
Create Date: 2026-08-16 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c3e91f4b28'
down_revision: Union[str, Sequence[str], None] = 'f2d9a4c8b613'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'install_beacon'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'trigger_install_beacon'")


def downgrade() -> None:
    """Downgrade schema."""
    # No downgrade path for an added enum value — same posture as every
    # prior enum-value migration here.
    pass
