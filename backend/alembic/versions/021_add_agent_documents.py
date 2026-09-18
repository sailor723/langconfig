"""add agent_documents table for DB-mode formal document persistence

DB mode (STORAGE_MODE=db) persists an agent's formal documents into a
dedicated table instead of loose files on disk. Agents write them through
the ``save_document`` built-in tool.

Revision ID: 021_add_agent_documents
Revises: 020_remove_export_system
Create Date: 2026-08-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '021_add_agent_documents'
down_revision = '020_remove_export_system'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the agent_documents table."""
    op.create_table(
        'agent_documents',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id'), nullable=True, index=True),
        sa.Column('agent_id', sa.Integer(),
                  sa.ForeignKey('deep_agent_templates.id'), nullable=True, index=True),
        sa.Column('execution_id', sa.String(length=100), nullable=True, index=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('doc_type', sa.String(length=50), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_agent_documents_project_title', 'agent_documents', ['project_id', 'title']
    )
    op.create_index(
        'ix_agent_documents_agent_title', 'agent_documents', ['agent_id', 'title']
    )


def downgrade() -> None:
    """Drop the agent_documents table (best-effort restore)."""
    op.drop_index('ix_agent_documents_agent_title', table_name='agent_documents')
    op.drop_index('ix_agent_documents_project_title', table_name='agent_documents')
    op.drop_table('agent_documents')
