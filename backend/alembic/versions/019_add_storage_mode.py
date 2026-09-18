"""add storage_mode column to settings table

Phase 5 of the "DB as the permanent store" strategy
(docs/system-architecture.md §15). Persists the runtime storage-mode
switch made in the Settings UI so it survives restarts. Nullable —
None means "use the .env / default value" (default is local disk).

Revision ID: 019_add_storage_mode
Revises: 018_add_storage_objects
Create Date: 2026-08-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '019_add_storage_mode'
down_revision = '018_add_storage_objects'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add storage_mode column (idempotent existence check)."""
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'settings' AND column_name = 'storage_mode')"
    )).scalar()

    if not exists:
        op.add_column(
            'settings',
            sa.Column('storage_mode', sa.String(20), nullable=True),
        )
        print("Added settings.storage_mode column")
    else:
        print("Note: settings.storage_mode already exists, skipping")


def downgrade() -> None:
    """Remove storage_mode column."""
    op.drop_column('settings', 'storage_mode')
