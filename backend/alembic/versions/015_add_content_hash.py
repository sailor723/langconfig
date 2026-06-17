"""add content_hash column to context_documents for SHA256 dedup

Revision ID: 015_add_content_hash
Revises: 014_conversation_archives
Create Date: 2026-06-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '015_add_content_hash'
down_revision = '014_conversation_archives'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add content_hash column to context_documents."""
    op.add_column(
        'context_documents',
        sa.Column('content_hash', sa.String(64), nullable=True),
    )
    op.create_index('ix_context_documents_content_hash', 'context_documents', ['content_hash'])


def downgrade() -> None:
    """Remove content_hash column."""
    op.drop_index('ix_context_documents_content_hash', table_name='context_documents')
    op.drop_column('context_documents', 'content_hash')
