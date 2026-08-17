"""add auto-created Library environment per content view

Revision ID: a3f9e21c6d84
Revises: f4a8c37e5d92
Create Date: 2026-08-18 06:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f9e21c6d84'
down_revision: Union[str, Sequence[str], None] = 'f4a8c37e5d92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'lifecycle_environments',
        sa.Column('is_library', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # name/(path_name, position) uniqueness moves from GLOBAL to scoped
    # per content_view_id — every content view's root is now literally
    # named "Library", which a global name constraint would reject on the
    # second content view. content_view_id itself STAYS nullable at the
    # DB level (see models.py's LifecycleEnvironment docstring) —
    # existing rows with content_view_id IS NULL are left as-is, not
    # backfilled or deleted; the application enforces "always set on
    # create" going forward, not a DB NOT NULL constraint, specifically
    # so this migration stays non-destructive.
    op.drop_constraint('lifecycle_environments_name_key', 'lifecycle_environments', type_='unique')
    op.drop_constraint('lifecycle_environments_path_name_position_key', 'lifecycle_environments', type_='unique')
    op.create_unique_constraint(
        'uq_lifecycle_environments_content_view_id_name', 'lifecycle_environments', ['content_view_id', 'name']
    )
    op.create_unique_constraint(
        'uq_lifecycle_environments_content_view_id_path_name_position',
        'lifecycle_environments',
        ['content_view_id', 'path_name', 'position'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'uq_lifecycle_environments_content_view_id_path_name_position', 'lifecycle_environments', type_='unique'
    )
    op.drop_constraint('uq_lifecycle_environments_content_view_id_name', 'lifecycle_environments', type_='unique')
    op.create_unique_constraint('lifecycle_environments_path_name_position_key', 'lifecycle_environments', ['path_name', 'position'])
    op.create_unique_constraint('lifecycle_environments_name_key', 'lifecycle_environments', ['name'])
    op.drop_column('lifecycle_environments', 'is_library')
