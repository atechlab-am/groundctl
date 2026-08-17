"""split content view assignment out of lifecycle_environments into a new
environment_content_views join table — an environment is now pure
promotion-path structure, and any number of content views can be
independently assigned/promoted within it (see models.py's
LifecycleEnvironment/EnvironmentContentView docstrings).

Revision ID: b8e34f0a9c17
Revises: a3f9e21c6d84
Create Date: 2026-08-24 09:00:00.000000

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8e34f0a9c17'
down_revision: Union[str, Sequence[str], None] = 'a3f9e21c6d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'assign_content_view_to_environment'")
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'unassign_content_view_from_environment'")

    op.create_table(
        'environment_content_views',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('environment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('lifecycle_environments.id'), nullable=False),
        sa.Column('content_view_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('content_views.id'), nullable=False),
        sa.Column('current_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('content_view_versions.id'), nullable=True),
        sa.Column('release', sa.String(), nullable=True),
        sa.Column('publish_prefix', sa.String(), nullable=True, unique=True),
        sa.Column('gpg_key_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('environment_id', 'content_view_id', name='uq_environment_content_views_environment_id_content_view_id'),
    )

    conn = op.get_bind()

    # Data migration: every existing lifecycle_environments row with a
    # non-null content_view_id (every row created under this session's
    # Library-per-content-view design, including every auto-created
    # "Library" row) becomes one environment_content_views row carrying
    # over its content_view_id/release/publish_prefix/current_version_id/
    # gpg_key_id — no data loss, every previously-published environment
    # stays published under the same publish_prefix.
    rows = conn.execute(
        sa.text(
            """
            SELECT id, content_view_id, release, publish_prefix, current_version_id, gpg_key_id, created_at, updated_at
            FROM lifecycle_environments
            WHERE content_view_id IS NOT NULL
            """
        )
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO environment_content_views
                    (id, environment_id, content_view_id, current_version_id, release, publish_prefix, gpg_key_id, created_at, updated_at)
                VALUES
                    (:id, :environment_id, :content_view_id, :current_version_id, :release, :publish_prefix, :gpg_key_id, :created_at, :updated_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "environment_id": str(row.id),
                "content_view_id": str(row.content_view_id),
                "current_version_id": str(row.current_version_id) if row.current_version_id else None,
                "release": row.release,
                "publish_prefix": row.publish_prefix,
                "gpg_key_id": row.gpg_key_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )

    # Every environment created this session was scoped to (content_view_id,
    # name) / (content_view_id, path_name, position) — e.g. every content
    # view's own "Library" row shares the literal name "Library" and
    # path_name="Library"/position=0. Restoring GLOBAL uniqueness below
    # would collide on the second such row, so rename every row after the
    # first (per duplicate name / per duplicate (path_name, position)) by
    # suffixing it with a short slice of its own id — deterministic,
    # collision-free, and the row is still fully identifiable by id
    # afterward for anyone who needs to reconcile it by hand.
    dup_names = conn.execute(
        sa.text(
            """
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY name ORDER BY created_at, id) AS rn
                FROM lifecycle_environments
            ) t WHERE rn > 1
            """
        )
    ).fetchall()
    for row in dup_names:
        conn.execute(
            sa.text("UPDATE lifecycle_environments SET name = name || '-' || substr(id::text, 1, 8) WHERE id = :id"),
            {"id": str(row.id)},
        )

    dup_paths = conn.execute(
        sa.text(
            """
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY path_name, position ORDER BY created_at, id) AS rn
                FROM lifecycle_environments
            ) t WHERE rn > 1
            """
        )
    ).fetchall()
    for row in dup_paths:
        conn.execute(
            sa.text(
                "UPDATE lifecycle_environments SET path_name = path_name || '-' || substr(id::text, 1, 8) WHERE id = :id"
            ),
            {"id": str(row.id)},
        )

    op.drop_constraint('lifecycle_environments_content_view_id_fkey', 'lifecycle_environments', type_='foreignkey')
    op.drop_constraint('lifecycle_environments_current_version_id_fkey', 'lifecycle_environments', type_='foreignkey')
    op.drop_constraint('uq_lifecycle_environments_content_view_id_name', 'lifecycle_environments', type_='unique')
    op.drop_constraint(
        'uq_lifecycle_environments_content_view_id_path_name_position', 'lifecycle_environments', type_='unique'
    )
    op.drop_constraint('lifecycle_environments_publish_prefix_key', 'lifecycle_environments', type_='unique')
    op.drop_column('lifecycle_environments', 'content_view_id')
    op.drop_column('lifecycle_environments', 'is_library')
    op.drop_column('lifecycle_environments', 'release')
    op.drop_column('lifecycle_environments', 'publish_prefix')
    op.drop_column('lifecycle_environments', 'current_version_id')
    op.drop_column('lifecycle_environments', 'gpg_key_id')

    op.create_unique_constraint('lifecycle_environments_name_key', 'lifecycle_environments', ['name'])
    op.create_unique_constraint(
        'lifecycle_environments_path_name_position_key', 'lifecycle_environments', ['path_name', 'position']
    )


def downgrade() -> None:
    """Downgrade schema. Reintroduces the five columns and copies back, per
    environment, whichever environment_content_views row was created first
    (an environment may have gained several assignments under the new
    model — only the first can be represented, since the old schema had
    room for exactly one content view per environment; this is a lossy
    downgrade for any environment with more than one assignment, same as
    any schema narrowing).
    """
    op.drop_constraint('lifecycle_environments_path_name_position_key', 'lifecycle_environments', type_='unique')
    op.drop_constraint('lifecycle_environments_name_key', 'lifecycle_environments', type_='unique')

    op.add_column('lifecycle_environments', sa.Column('content_view_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        'lifecycle_environments', sa.Column('is_library', sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column('lifecycle_environments', sa.Column('release', sa.String(), nullable=True))
    op.add_column('lifecycle_environments', sa.Column('publish_prefix', sa.String(), nullable=True))
    op.add_column(
        'lifecycle_environments', sa.Column('current_version_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column('lifecycle_environments', sa.Column('gpg_key_id', sa.String(), nullable=True))

    conn = op.get_bind()
    first_per_env = conn.execute(
        sa.text(
            """
            SELECT DISTINCT ON (environment_id)
                environment_id, content_view_id, current_version_id, release, publish_prefix, gpg_key_id
            FROM environment_content_views
            ORDER BY environment_id, created_at, id
            """
        )
    ).fetchall()
    for row in first_per_env:
        conn.execute(
            sa.text(
                """
                UPDATE lifecycle_environments
                SET content_view_id = :content_view_id,
                    current_version_id = :current_version_id,
                    release = :release,
                    publish_prefix = :publish_prefix,
                    gpg_key_id = :gpg_key_id
                WHERE id = :environment_id
                """
            ),
            {
                "environment_id": str(row.environment_id),
                "content_view_id": str(row.content_view_id),
                "current_version_id": str(row.current_version_id) if row.current_version_id else None,
                "release": row.release,
                "publish_prefix": row.publish_prefix,
                "gpg_key_id": row.gpg_key_id,
            },
        )

    op.create_foreign_key(
        'lifecycle_environments_content_view_id_fkey', 'lifecycle_environments', 'content_views', ['content_view_id'], ['id']
    )
    op.create_foreign_key(
        'lifecycle_environments_current_version_id_fkey',
        'lifecycle_environments',
        'content_view_versions',
        ['current_version_id'],
        ['id'],
    )
    op.create_unique_constraint('lifecycle_environments_publish_prefix_key', 'lifecycle_environments', ['publish_prefix'])
    op.create_unique_constraint(
        'uq_lifecycle_environments_content_view_id_name', 'lifecycle_environments', ['content_view_id', 'name']
    )
    op.create_unique_constraint(
        'uq_lifecycle_environments_content_view_id_path_name_position',
        'lifecycle_environments',
        ['content_view_id', 'path_name', 'position'],
    )

    op.drop_table('environment_content_views')
