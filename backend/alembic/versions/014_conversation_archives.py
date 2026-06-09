"""add conversation_archives and user_profiles tables

Revision ID: 014_conversation_archives
Revises: 013_workflow_triggers
Create Date: 2026-06-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '014_conversation_archives'
down_revision = '014_agent_memories'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create conversation_archives and user_profiles tables."""
    # conversation_archives — append-only log of all chat turns
    op.create_table(
        'conversation_archives',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', sa.String(255), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), nullable=False, index=True),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('user_message', sa.Text(), nullable=False),
        sa.Column('agent_response', sa.Text(), nullable=False),
        sa.Column('tool_calls', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        'idx_archives_session_turn',
        'conversation_archives',
        ['session_id', 'turn_number'],
        unique=True,
    )

    # user_profiles — auto-extracted user metadata
    op.create_table(
        'user_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, unique=True, index=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('preferences', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('metadata_snapshot', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column(
            'first_seen_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    """Drop conversation_archives and user_profiles tables."""
    op.drop_table('conversation_archives')
    op.drop_table('user_profiles')
