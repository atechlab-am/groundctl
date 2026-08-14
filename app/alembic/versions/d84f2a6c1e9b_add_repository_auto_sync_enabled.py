"""add repository auto_sync_enabled

Revision ID: d84f2a6c1e9b
Revises: b3f6d29e4a17
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd84f2a6c1e9b'
down_revision: Union[str, Sequence[str], None] = 'b3f6d29e4a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default so this is safe against a table with existing rows —
    # every pre-existing repository becomes auto_sync_enabled=true, which
    # matches its actual current behavior (the nightly sweep already syncs
    # it unconditionally today; this column only starts gating it once the
    # app code that reads it ships).
    op.add_column(
        'repositories',
        sa.Column('auto_sync_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column('repositories', 'auto_sync_enabled', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('repositories', 'auto_sync_enabled')
