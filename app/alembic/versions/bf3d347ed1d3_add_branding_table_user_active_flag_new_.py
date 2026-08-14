"""add branding table, user active flag, new audit actions

Revision ID: bf3d347ed1d3
Revises: 01773abb6cf1
Create Date: 2026-08-06 12:40:01.819392

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bf3d347ed1d3'
down_revision: Union[str, Sequence[str], None] = '01773abb6cf1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('branding',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('primary_color', sa.String(), nullable=True),
    sa.Column('accent_color', sa.String(), nullable=True),
    sa.Column('logo_data', sa.LargeBinary(), nullable=True),
    sa.Column('logo_content_type', sa.String(), nullable=True),
    sa.Column('favicon_data', sa.LargeBinary(), nullable=True),
    sa.Column('favicon_content_type', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    # server_default so this is safe against a table with existing rows —
    # autogenerate's plain `nullable=False` with no default would fail on
    # any install with users already created (every real deployment).
    # Every pre-existing user becomes active=true, correct: nothing was
    # ever deactivated before this column existed.
    op.add_column('users', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column('users', 'active', server_default=None)

    # Postgres enums can't have a value added and used in the same
    # transaction Alembic wraps migrations in by default — ALTER TYPE ...
    # ADD VALUE must be committed before any row can reference the new
    # value. autocommit_block() runs this statement outside the migration's
    # normal transaction.
    with op.get_context().autocommit_block():
        for value in ("update_user", "deactivate_user", "reactivate_user", "change_own_password", "update_branding"):
            op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE — downgrading the enum
    # would require rebuilding the type and every column that uses it.
    # Not attempted here: no migration in this project has needed a real
    # downgrade path yet (see 0001_initial.py's own precedent), and the
    # new audit_action values are additive/inert on a downgrade (nothing
    # reads them if the app code that wrote them is also reverted).
    op.drop_column('users', 'active')
    op.drop_table('branding')
