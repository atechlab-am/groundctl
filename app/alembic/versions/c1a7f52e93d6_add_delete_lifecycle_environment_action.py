"""add delete_lifecycle_environment audit action

Revision ID: c1a7f52e93d6
Revises: b8e34f0a9c17
Create Date: 2026-08-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1a7f52e93d6'
down_revision: Union[str, Sequence[str], None] = 'b8e34f0a9c17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'delete_lifecycle_environment'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres cannot cheaply remove an enum label — same accepted
    # no-op-downgrade posture as every other enum-value-only migration
    # in this project (e.g. f4a8c37e5d92, b8e34f0a9c17). The leftover
    # value is harmless if never used going forward.
    pass
