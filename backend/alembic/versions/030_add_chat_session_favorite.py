"""add chat_sessions.is_favorite (pinned conversations)

Adds the per-session "favourite" flag behind the chat history's pinned list:
users mark a conversation and it stays at the top of the sidebar for quick
select. Independent of titles, which is the point — repeated test runs of the
same agent produce near-identical titles, so pinning has to be explicit.

`favorited_at` keeps the pinned order stable (newest pin first) instead of
re-sorting every time a pinned conversation receives a message.

Revision ID: 030_chat_session_favorite
Revises: 029_add_tool_definition
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '030_chat_session_favorite'
down_revision = '029_add_tool_definition'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default keeps existing rows valid without a data backfill; the
    # default stays so inserts that omit the column (legacy code paths) work.
    op.add_column(
        'chat_sessions',
        sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column(
        'chat_sessions',
        sa.Column('favorited_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_chat_sessions_is_favorite', 'chat_sessions', ['is_favorite'])


def downgrade() -> None:
    op.drop_index('ix_chat_sessions_is_favorite', table_name='chat_sessions')
    op.drop_column('chat_sessions', 'favorited_at')
    op.drop_column('chat_sessions', 'is_favorite')
