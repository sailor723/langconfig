"""clear legacy model-parameter values — .env is the single source of truth

The settings row carried baked-in legacy values (temperature 0.7, max tokens
4096/3276) that shadowed .env (DEFAULT_TEMPERATURE=0, MAX_TOKENS=256000) in
the Settings UI. The model-parameter columns are now NULL-by-default, and
existing rows are cleared: the model-defaults endpoint falls back to .env
whenever the DB value is NULL, so the UI shows the .env truth unless the user
explicitly overrides it.

Revision ID: 027_clear_settings_model_params
Revises: 026_add_setup_complete
Create Date: 2026-08-15 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '027_clear_settings_model_params'
down_revision = '026_add_setup_complete'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """NULL out the legacy model-parameter values on the settings row."""
    op.execute(
        "UPDATE settings SET default_model = NULL, default_temperature = NULL, "
        "max_tokens = NULL, primary_model = NULL, temperature = NULL, "
        "max_tokens_default = NULL WHERE id = 1"
    )


def downgrade() -> None:
    """Restore the legacy defaults (best-effort)."""
    op.execute(
        "UPDATE settings SET default_temperature = 0.7, max_tokens = 4096, "
        "temperature = 0.7, max_tokens_default = 4096 WHERE id = 1"
    )
