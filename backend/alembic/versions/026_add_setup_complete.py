"""add settings.setup_complete — first-run onboarding flag

The single-row settings table gains a setup_complete boolean so the app can
show the first-time setup wizard only until the user has finished it (API key
+ workspace). Default False → existing installs see the wizard once.

Revision ID: 026_add_setup_complete
Revises: 025_drop_project_number
Create Date: 2026-08-14 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '026_add_setup_complete'
down_revision = '025_drop_project_number'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the setup_complete column (idempotent)."""
    op.execute(
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS setup_complete BOOLEAN "
        "NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    """Drop the column."""
    op.execute("ALTER TABLE settings DROP COLUMN IF EXISTS setup_complete")
