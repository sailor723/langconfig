"""add is_builtin column to custom_tools for DB-backed built-in tools

Built-in tools (previously hardcoded in tools/native_tools.py) are now seeded
into the custom_tools table as ``is_builtin`` rows so agents compile and run
tools uniformly from the database via ToolFactory.

Revision ID: 016_add_builtin_tools
Revises: 015_add_content_hash
Create Date: 2026-08-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '016_add_builtin_tools'
down_revision = '015_add_content_hash'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add is_builtin flag to custom_tools (system-seeded built-in tools)."""
    op.add_column(
        'custom_tools',
        sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    """Remove is_builtin column."""
    op.drop_column('custom_tools', 'is_builtin')
