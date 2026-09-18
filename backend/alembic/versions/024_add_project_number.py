"""add user-visible project number (vault folder key)

Projects get a user-facing ``number`` (separate from the DB ``id``) used as
the vault folder key: outputs/projects/{number}/… . Backfilled to ``id`` so
existing vault folders keep their names. All DB references (FKs, chat
sessions, knowledge, memory, tools) continue to use ``id``.

Revision ID: 024_add_project_number
Revises: 023_add_vault_workspace_fields
Create Date: 2026-08-14 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '024_add_project_number'
down_revision = '023_add_vault_workspace_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the number column, unique index, and backfill number = id."""
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS number INTEGER")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_number "
        "ON projects (number) WHERE number IS NOT NULL"
    )
    # Backfill keeps existing vault folders stable (folder key = number).
    op.execute("UPDATE projects SET number = id WHERE number IS NULL")


def downgrade() -> None:
    """Drop the number column."""
    op.execute("DROP INDEX IF EXISTS ix_projects_number")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS number")
