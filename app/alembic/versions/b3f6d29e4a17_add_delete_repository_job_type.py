"""add delete_repository job type

Revision ID: b3f6d29e4a17
Revises: a91d5c3e7f04
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3f6d29e4a17'
down_revision: Union[str, Sequence[str], None] = 'a91d5c3e7f04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'delete_repository'")
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'update_repository'")


def downgrade() -> None:
    """Downgrade schema."""
    # No downgrade path for an added enum value — same posture as every
    # prior enum-value migration here.
    pass
