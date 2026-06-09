# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""add agent_memories table

Revision ID: 014_agent_memories
Revises: 013_workflow_triggers
Create Date: 2026-06-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "014_agent_memories"
down_revision = "013_workflow_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create agent_memories table for persistent agent memory."""

    # Check if table already exists (idempotent)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'agent_memories')"
        )
    )
    if result.scalar():
        return

    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(255),
            nullable=False,
            comment="Agent identifier, e.g. 'task_42'",
        ),
        sa.Column(
            "memory_type",
            sa.String(50),
            nullable=False,
            server_default="fact",
            comment="fact/decision/pattern/learning/context/relationship",
        ),
        sa.Column(
            "importance",
            sa.Integer(),
            nullable=False,
            server_default="5",
            comment="1-10 importance score",
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            default=list,
            comment="Optional tags for categorization",
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="The memory content",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes
    op.create_index("ix_agent_memories_agent_id", "agent_memories", ["agent_id"])
    op.create_index(
        "ix_agent_memories_project_agent",
        "agent_memories",
        ["project_id", "agent_id", "created_at"],
    )


def downgrade() -> None:
    """Drop agent_memories table."""
    op.drop_table("agent_memories")