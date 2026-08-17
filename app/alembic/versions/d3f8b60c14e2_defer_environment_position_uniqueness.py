"""make lifecycle_environments (path_name, position) uniqueness deferrable

Revision ID: d3f8b60c14e2
Revises: c1a7f52e93d6
Create Date: 2026-08-31 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3f8b60c14e2'
down_revision: Union[str, Sequence[str], None] = 'c1a7f52e93d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # create_lifecycle_environment's insert-with-shift (lifecycle_environments.py)
    # bulk-UPDATEs every environment at position >= the insertion point up by
    # one, in the same statement as the new row's INSERT. Postgres checks a
    # NOT DEFERRABLE unique constraint after each row is written, not at
    # statement/transaction end — shifting b(4->5) while c is still at 5
    # trips "duplicate key" even though the end state is perfectly valid.
    # DEFERRABLE INITIALLY DEFERRED defers the check to COMMIT, which is
    # exactly the semantics this shift needs. Postgres requires dropping
    # and recreating the constraint to change this property; there is no
    # ALTER TABLE ... ALTER CONSTRAINT for deferrability pre-15, so this
    # uses the portable drop+recreate form.
    op.drop_constraint('lifecycle_environments_path_name_position_key', 'lifecycle_environments', type_='unique')
    op.create_unique_constraint(
        'lifecycle_environments_path_name_position_key',
        'lifecycle_environments',
        ['path_name', 'position'],
        deferrable=True,
        initially='DEFERRED',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('lifecycle_environments_path_name_position_key', 'lifecycle_environments', type_='unique')
    op.create_unique_constraint(
        'lifecycle_environments_path_name_position_key', 'lifecycle_environments', ['path_name', 'position']
    )
