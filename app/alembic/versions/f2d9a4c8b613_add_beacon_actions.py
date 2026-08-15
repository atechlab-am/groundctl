"""add beacon_actions table

Revision ID: f2d9a4c8b613
Revises: e8b31c5a7f04
Create Date: 2026-08-16 04:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2d9a4c8b613'
down_revision: Union[str, Sequence[str], None] = 'e8b31c5a7f04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # sa.Enum inline in create_table auto-creates the Postgres type — same
    # pattern as every enum column in 0001_initial.py, no separate
    # CREATE TYPE step needed.
    op.create_table(
        'beacon_actions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('server_id', sa.UUID(), nullable=False),
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'delivered', 'succeeded', 'failed', 'cancelled', 'timed_out', name='beacon_action_status'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_beacon_actions_server_id', 'beacon_actions', ['server_id'])
    op.create_index('ix_beacon_actions_job_id', 'beacon_actions', ['job_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_beacon_actions_job_id', table_name='beacon_actions')
    op.drop_index('ix_beacon_actions_server_id', table_name='beacon_actions')
    op.drop_table('beacon_actions')
    sa.Enum(name='beacon_action_status').drop(op.get_bind(), checkfirst=True)
