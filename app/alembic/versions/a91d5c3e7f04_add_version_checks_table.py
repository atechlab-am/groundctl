"""add version_checks table

Revision ID: a91d5c3e7f04
Revises: f2b8d64a1c93
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a91d5c3e7f04'
down_revision: Union[str, Sequence[str], None] = 'f2b8d64a1c93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'version_checks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('latest_version', sa.String(), nullable=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('check_failed', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('version_checks')
