"""add publish_and_promote job type and audit action

Revision ID: d1f6b83c2a94
Revises: c9e4b27a5f81
Create Date: 2026-08-16 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1f6b83c2a94'
down_revision: Union[str, Sequence[str], None] = 'c9e4b27a5f81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'publish_and_promote'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'trigger_publish_and_promote'")


def downgrade() -> None:
    """Downgrade schema."""
    # No downgrade path for an added enum value — same posture as every
    # prior enum-value migration here.
    pass
