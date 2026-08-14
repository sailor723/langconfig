"""add user-defined workspace_path to deep_agent_templates

Agents now carry an optional user-defined workspace path persisted in
PostgreSQL. When set, chat uploads + generated files for the agent live
under that directory; when null the runtime falls back to the default
``outputs/agents/agent_{id}/`` convention.

Revision ID: 022_add_agent_workspace_path
Revises: 021_add_agent_documents
Create Date: 2026-08-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '022_add_agent_workspace_path'
down_revision = '021_add_agent_documents'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the workspace_path column (idempotent)."""
    op.execute(
        "ALTER TABLE deep_agent_templates "
        "ADD COLUMN IF NOT EXISTS workspace_path VARCHAR(500)"
    )


def downgrade() -> None:
    """Drop the workspace_path column."""
    op.execute(
        "ALTER TABLE deep_agent_templates DROP COLUMN IF EXISTS workspace_path"
    )
