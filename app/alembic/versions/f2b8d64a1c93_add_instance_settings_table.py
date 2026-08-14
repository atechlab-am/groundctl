"""add instance_settings table and update_instance_settings audit action

Revision ID: f2b8d64a1c93
Revises: e7a3c15f9b2d
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2b8d64a1c93'
down_revision: Union[str, Sequence[str], None] = 'e7a3c15f9b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'instance_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('audit_log_retention_days', sa.Integer(), nullable=True),
        sa.Column('activation_key_default_ttl_hours', sa.Integer(), nullable=True),
        sa.Column('stale_checkin_hours', sa.Integer(), nullable=True),
        sa.Column('relay_stale_threshold_hours', sa.Integer(), nullable=True),
        sa.Column('disk_usage_warn_percent', sa.Float(), nullable=True),
        sa.Column('webhook_url', sa.String(), nullable=True),
        sa.Column('webhook_secret', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'update_instance_settings'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('instance_settings')
    # No downgrade path for the added enum value — same posture as every
    # prior enum-value migration here.
