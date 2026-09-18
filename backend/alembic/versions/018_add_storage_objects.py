"""create storage_objects table for the StorageBackend seam

Phase 1 of the "DB as the permanent store" strategy
(docs/system-architecture.md §15). BYTEA blobs addressed by a unique key.

Revision ID: 018_add_storage_objects
Revises: 017_add_builtin_tool_metadata
Create Date: 2026-08-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '018_add_storage_objects'
down_revision = '017_add_builtin_tool_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create storage_objects table (idempotent existence check)."""
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'storage_objects')"
    )).scalar()

    if not exists:
        op.create_table(
            'storage_objects',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('key', sa.String(500), nullable=False, unique=True),
            sa.Column('content', sa.LargeBinary(), nullable=False),  # BYTEA
            sa.Column('size_bytes', sa.BigInteger(), nullable=False, default=0),
            sa.Column('mime_type', sa.String(100), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        print("Created storage_objects table")
    else:
        print("Note: storage_objects table already exists, skipping creation")


def downgrade() -> None:
    """Remove storage_objects table."""
    op.drop_table('storage_objects')
