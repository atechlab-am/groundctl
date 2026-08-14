"""add products table, repository product_id/package_count, instance_setting repository_stale_threshold_hours

Revision ID: f7c3b19d4e02
Revises: e5c9a173f2b8
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7c3b19d4e02'
down_revision: Union[str, Sequence[str], None] = 'e5c9a173f2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same autocommit_block requirement as every prior enum-value addition
    # here (e.g. e7a3c15f9b2d) — must commit before any row can reference
    # it. Missing this in the original version of this migration is why
    # AuditLog inserts for create_product/update_product/delete_product
    # failed with "invalid input value for enum audit_action" — the Python
    # AuditAction enum gained the members but the Postgres enum type never
    # did.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'create_product'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'update_product'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'delete_product'")

    op.create_table(
        'products',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.add_column('repositories', sa.Column('product_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'repositories_product_id_fkey', 'repositories', 'products', ['product_id'], ['id']
    )
    op.add_column('repositories', sa.Column('package_count', sa.Integer(), nullable=True))

    op.add_column(
        'instance_settings', sa.Column('repository_stale_threshold_hours', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('instance_settings', 'repository_stale_threshold_hours')
    op.drop_column('repositories', 'package_count')
    op.drop_constraint('repositories_product_id_fkey', 'repositories', type_='foreignkey')
    op.drop_column('repositories', 'product_id')
    op.drop_table('products')
