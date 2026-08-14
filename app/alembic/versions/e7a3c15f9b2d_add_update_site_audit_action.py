"""add update_site audit action

Revision ID: e7a3c15f9b2d
Revises: c4a1f9b2e7d5
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7a3c15f9b2d'
down_revision: Union[str, Sequence[str], None] = 'c4a1f9b2e7d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same autocommit_block requirement as bf3d347ed1d3/c4a1f9b2e7d5's own
    # enum-value additions — must commit before any row can reference it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'update_site'")


def downgrade() -> None:
    """Downgrade schema."""
    # No downgrade path for an added enum value (Postgres has no ALTER TYPE
    # ... DROP VALUE) — same posture as every prior enum-value migration here.
    pass
