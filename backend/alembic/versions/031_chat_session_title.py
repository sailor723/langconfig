"""add chat_sessions.title (conversation names)

Titles were the missing piece of the chat history: rows showed the last
message's preview, which mutates as the conversation grows, and the open chat
had no name at all.

`title` is nullable on purpose — a null title means "fall back to the first user
message", so every conversation is readable immediately and a name is stored
only when the user renames one. `title_source` ('manual' | 'auto') records who
chose it, so a future auto-titler can fill in the gaps without ever overwriting
a name the user typed.

Revision ID: 031_chat_session_title
Revises: 030_chat_session_favorite
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '031_chat_session_title'
down_revision = '030_chat_session_favorite'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_sessions', sa.Column('title', sa.String(length=120), nullable=True))
    op.add_column('chat_sessions', sa.Column('title_source', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_sessions', 'title_source')
    op.drop_column('chat_sessions', 'title')
