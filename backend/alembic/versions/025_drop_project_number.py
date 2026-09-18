"""drop projects.number — vault folder key is the project name, not a number

024 added projects.number as the vault folder key; the user wants the folder
named by the project name (sanitized) instead. This reverts the column; the
folder-key resolution moves to the sanitized project name.

Revision ID: 025_drop_project_number
Revises: 024_add_project_number
Create Date: 2026-08-14 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '025_drop_project_number'
down_revision = '024_add_project_number'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the number column and its index."""
    op.execute("DROP INDEX IF EXISTS ix_projects_number")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS number")


def downgrade() -> None:
    """Re-add the column (no backfill — use 024 semantics)."""
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS number INTEGER")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_number "
        "ON projects (number) WHERE number IS NOT NULL"
    )
    op.execute("UPDATE projects SET number = id WHERE number IS NULL")
