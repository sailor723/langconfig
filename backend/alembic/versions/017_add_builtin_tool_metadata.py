"""add requires_api_key column to custom_tools for built-in tool metadata

The tool registry is now DB-primary: seeded built-in tools carry their UI
metadata (display name, category, requires_api_key) in the row itself, so the
frontend no longer depends on the hardcoded TOOL_REGISTRY in
tools/native_tools.py for the 43 seedable tools.

Revision ID: 017_add_builtin_tool_metadata
Revises: 016_add_builtin_tools
Create Date: 2026-08-01 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017_add_builtin_tool_metadata'
down_revision = '016_add_builtin_tools'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add requires_api_key to custom_tools (env var name, or NULL if none)."""
    op.add_column(
        'custom_tools',
        sa.Column('requires_api_key', sa.String(100), nullable=True),
    )


def downgrade() -> None:
    """Remove requires_api_key column."""
    op.drop_column('custom_tools', 'requires_api_key')
