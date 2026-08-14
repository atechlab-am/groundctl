"""add repository last_job_id

Revision ID: e5c9a173f2b8
Revises: d84f2a6c1e9b
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5c9a173f2b8'
down_revision: Union[str, Sequence[str], None] = 'd84f2a6c1e9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('repositories', sa.Column('last_job_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'repositories_last_job_id_fkey', 'repositories', 'jobs', ['last_job_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('repositories_last_job_id_fkey', 'repositories', type_='foreignkey')
    op.drop_column('repositories', 'last_job_id')
