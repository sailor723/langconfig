"""vault-scoped agent workspace: chat_sessions.project_id + agent_docs

1. chat_sessions.project_id — binds a chat session to the active vault
   (project), so uploads + generated files resolve per (vault, agent).
2. deep_agent_templates.agent_docs — user-authored agent instruction docs
   ({"AGENTS.md": "...", "CLAUDE.md": "..."}); PostgreSQL is the source of
   truth, materialized into the agent workspace at chat build time.

Revision ID: 023_add_vault_workspace_fields
Revises: 022_add_agent_workspace_path
Create Date: 2026-08-14 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '023_add_vault_workspace_fields'
down_revision = '022_add_agent_workspace_path'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the two columns (idempotent)."""
    op.execute(
        "ALTER TABLE chat_sessions "
        "ADD COLUMN IF NOT EXISTS project_id INTEGER "
        "REFERENCES projects(id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_project_id "
        "ON chat_sessions (project_id)"
    )
    op.execute(
        "ALTER TABLE deep_agent_templates "
        "ADD COLUMN IF NOT EXISTS agent_docs JSON"
    )


def downgrade() -> None:
    """Drop the two columns."""
    op.execute(
        "ALTER TABLE chat_sessions DROP COLUMN IF EXISTS project_id"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_chat_sessions_project_id"
    )
    op.execute(
        "ALTER TABLE deep_agent_templates DROP COLUMN IF EXISTS agent_docs"
    )
