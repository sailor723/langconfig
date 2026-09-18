"""remove export system: drop agent_exports table + workflow export columns

Removes the folder-based export system's remaining database footprint:
- the `agent_exports` table (AgentExport model — deleted)
- the `workflow_profiles.export_status / export_error / last_export_at`
  columns (auto-export tracking — feature removed)

Revision ID: 020_remove_export_system
Revises: 019_add_storage_mode
Create Date: 2026-08-03 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '020_remove_export_system'
down_revision = '019_add_storage_mode'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the export-system tables/columns."""
    # Drop the FK-referencing table first (no other tables reference it).
    op.drop_table('agent_exports')
    op.drop_column('workflow_profiles', 'export_status')
    op.drop_column('workflow_profiles', 'export_error')
    op.drop_column('workflow_profiles', 'last_export_at')


def downgrade() -> None:
    """Recreate the export-system schema (best-effort restore)."""
    op.add_column('workflow_profiles', sa.Column(
        'export_status', sa.String(length=50), nullable=True
    ))
    op.add_column('workflow_profiles', sa.Column(
        'export_error', sa.Text(), nullable=True
    ))
    op.add_column('workflow_profiles', sa.Column(
        'last_export_at', sa.DateTime(timezone=True), nullable=True
    ))
    op.create_table(
        'agent_exports',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('agent_id', sa.Integer(),
                  sa.ForeignKey('deep_agent_templates.id'), nullable=False),
        sa.Column('export_type', sa.String(length=50), nullable=False),
        sa.Column('export_format', sa.String(length=50), nullable=True),
        sa.Column('export_config', sa.JSON(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('generated_files', sa.JSON(), nullable=True),
        sa.Column('download_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_downloaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
