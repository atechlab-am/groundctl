"""simplify lifecycle environment creation — defer content_view/release/
publish_prefix to first promote, drop dead distro column, add description

Revision ID: f4a8c37e5d92
Revises: e2b7a94f6c15
Create Date: 2026-08-17 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4a8c37e5d92'
down_revision: Union[str, Sequence[str], None] = 'e2b7a94f6c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('lifecycle_environments', sa.Column('description', sa.Text(), nullable=True))
    op.alter_column('lifecycle_environments', 'content_view_id', existing_type=sa.UUID(), nullable=True)
    op.alter_column('lifecycle_environments', 'release', existing_type=sa.String(), nullable=True)
    op.alter_column('lifecycle_environments', 'publish_prefix', existing_type=sa.String(), nullable=True)
    # distro was write-only — never read anywhere in the codebase
    # (render_apt_source only takes `release`) — dropped rather than
    # carried forward as another deferred/derived field.
    op.drop_column('lifecycle_environments', 'distro')
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'update_lifecycle_environment'")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('lifecycle_environments', sa.Column('distro', sa.String(), nullable=False, server_default='ubuntu'))
    op.alter_column('lifecycle_environments', 'publish_prefix', existing_type=sa.String(), nullable=False)
    op.alter_column('lifecycle_environments', 'release', existing_type=sa.String(), nullable=False)
    op.alter_column('lifecycle_environments', 'content_view_id', existing_type=sa.UUID(), nullable=False)
    op.drop_column('lifecycle_environments', 'description')
