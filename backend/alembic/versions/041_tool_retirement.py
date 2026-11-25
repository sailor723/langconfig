"""add custom_tools retirement columns — is_deprecated / superseded_by / deprecated_reason

Why: 88 seeded tools and no way to say "this one has a successor, stop offering it". The obvious lever,
``is_public``, carries no signal — it is false on every seeded row already — and deleting a row breaks the
agent configs, transcripts and seed snapshots that quote its ``tool_id``. So a tool retires the way an agent
does: mark it, keep the row, and let the registry stop listing it.

    is_deprecated     bool, default false — the picker stops offering it
    superseded_by     the successor's tool_id (e.g. pg_query → db_query), so "what do I use instead?" is a
                      lookup rather than a memory test
    deprecated_reason one line: why, and what breaks if someone still binds it

Revision ID: 041_tool_retirement
Revises: 040_user_nickname
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "041_tool_retirement"
down_revision = "040_user_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("custom_tools",
                  sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("custom_tools", sa.Column("superseded_by", sa.String(length=100), nullable=True))
    op.add_column("custom_tools", sa.Column("deprecated_reason", sa.Text(), nullable=True))
    op.create_index("ix_custom_tools_is_deprecated", "custom_tools", ["is_deprecated"])


def downgrade() -> None:
    op.drop_index("ix_custom_tools_is_deprecated", table_name="custom_tools")
    op.drop_column("custom_tools", "deprecated_reason")
    op.drop_column("custom_tools", "superseded_by")
    op.drop_column("custom_tools", "is_deprecated")
