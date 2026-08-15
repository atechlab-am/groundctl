"""add source column to compliance_records and server_facts, add last_facts_pushed_at to server_beacon_state

Revision ID: e8b31c5a7f04
Revises: d47a2f963e1c
Create Date: 2026-08-16 02:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e8b31c5a7f04'
down_revision: Union[str, Sequence[str], None] = 'd47a2f963e1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default backfills every existing row to "ssh" (accurate —
    # every row that exists before this migration WAS gathered via SSH,
    # since beacon facts push didn't exist yet) without a separate UPDATE
    # pass; nullable=False is safe immediately because of it.
    op.add_column(
        'compliance_records',
        sa.Column('source', sa.String(), nullable=False, server_default='ssh'),
    )
    op.add_column(
        'server_facts',
        sa.Column('source', sa.String(), nullable=False, server_default='ssh'),
    )
    op.add_column(
        'server_beacon_state',
        sa.Column('last_facts_pushed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('server_beacon_state', 'last_facts_pushed_at')
    op.drop_column('server_facts', 'source')
    op.drop_column('compliance_records', 'source')
