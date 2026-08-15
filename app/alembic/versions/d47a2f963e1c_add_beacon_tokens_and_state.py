"""add beacon_tokens and server_beacon_state tables, assign_server_environment/issue_beacon_token/revoke_beacon_token audit actions

Revision ID: d47a2f963e1c
Revises: c92e5d1a4f68
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd47a2f963e1c'
down_revision: Union[str, Sequence[str], None] = 'c92e5d1a4f68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same autocommit_block pattern as every prior enum-value addition here
    # (e.g. e7a3c15f9b2d, f7c3b19d4e02, a3d8e26f5c91) — must commit before
    # any row can reference it. assign_server_environment was actually added
    # in a prior migration (c92e5d1a4f68's predecessor chain never included
    # it — added here since it was introduced in models.py alongside this
    # work but the enum-value migration was missed at the time).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'assign_server_environment'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'issue_beacon_token'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'revoke_beacon_token'")

    op.create_table(
        'beacon_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('server_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_beacon_tokens_server_id', 'beacon_tokens', ['server_id'])

    op.create_table(
        'server_beacon_state',
        sa.Column('server_id', sa.UUID(), nullable=False),
        sa.Column('config_serial', sa.Integer(), nullable=False),
        sa.Column('applied_config_serial', sa.Integer(), nullable=True),
        sa.Column('last_checkin_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_apply_status', sa.String(), nullable=True),
        sa.Column('last_apply_detail', sa.Text(), nullable=True),
        sa.Column('agent_version', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id']),
        sa.PrimaryKeyConstraint('server_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('server_beacon_state')
    op.drop_index('ix_beacon_tokens_server_id', table_name='beacon_tokens')
    op.drop_table('beacon_tokens')
    # No downgrade path for an added enum value (Postgres has no ALTER TYPE
    # ... DROP VALUE) — same posture as every prior enum-value migration here.
