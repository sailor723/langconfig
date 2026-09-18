"""add custom_tools.definition — DSH-style tool definition (Phase A)

Adds the nullable ``definition`` JSON column to ``custom_tools`` carrying the
declarative tool definition (category, order, section, timeout_ms,
is_concurrency_safe, output_schema, guard, presentation — see
core/tools/definition.py and docs/tools-refactor.md). Nullable + backfilled
from tool_type so existing rows compile with sane defaults.

Revision ID: 029_add_tool_definition
Revises: 028_create_settings_documents
Create Date: 2026-08-15 00:00:00.000000
"""
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '029_add_tool_definition'
down_revision = '028_create_settings_documents'
branch_labels = None
depends_on = None


# tool_type -> category backfill (mirrors core/tools/definition.py vocabulary).
# Hardcoded constants — inlined as plain JSON literals (jsonb_set + `:x::type`
# casts both tripped Postgres/SQLAlchemy quirks).
_TYPE_CATEGORY = {
    "api": "web",
    "notification": "notification",
    "image_video": "custom",
    "database": "database",
    "data_transform": "custom",
    "python_function": "custom",
}


def upgrade() -> None:
    """Add the nullable definition column and backfill category from tool_type."""
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE custom_tools ADD COLUMN IF NOT EXISTS definition JSON"))
    for tool_type, category in _TYPE_CATEGORY.items():
        bind.execute(text(
            "UPDATE custom_tools SET definition = "
            f"'{{\"category\": \"{category}\"}}'::json "
            f"WHERE definition IS NULL AND tool_type = '{tool_type}'"
        ))
    # Default the rest to the custom category.
    bind.execute(text(
        "UPDATE custom_tools SET definition = "
        "'{\"category\": \"custom\"}'::json WHERE definition IS NULL"
    ))


def downgrade() -> None:
    """Drop the column."""
    op.execute("ALTER TABLE custom_tools DROP COLUMN IF EXISTS definition")
