"""add content_view_versions.package_count

Revision ID: b6f4e91a2d73
Revises: a3d8e26f5c91
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b6f4e91a2d73'
down_revision: Union[str, Sequence[str], None] = 'a3d8e26f5c91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('content_view_versions', sa.Column('package_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_view_versions', 'package_count')
