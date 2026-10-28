"""drop two dead columns on ``models`` — api_model_name, api_key

Both were declared for a design in which the model catalogue row carried its own
credentials and an internal provider name. Nothing ever wrote them, and this
audit found nothing that reads them either: a model row's credential is resolved
from ``settings_documents`` by *provider* (``config.get_api_key_from_db`` →
``models.api_keys``), and the upstream model name lives in ``model_id``.

Evidence at the time of writing (29 rows in ``models``):

    api_model_name   filled 0/29   referenced only by the ORM declaration and
                                   ``Model.to_dict()`` (which no caller reads)
    api_key          filled 0/29   referenced only by the ORM declaration; the
                                   ``api_key=`` arguments in
                                   ``api/models/routes.py`` come from settings

Why dropping is safe rather than merely tidy: a dead credential column is a
*trap*. The next person to wire "the model's own key" into the runtime would
reach for ``Model.api_key`` — a site-wide shared column — and silently bypass
the per-account key resolution added in migration 037. Removing the column
removes the shortcut.

Scope: two columns on one table. ``local_models.api_key`` is deliberately
**kept** — it has a live read/write path in ``api/models/local.py`` and is the
credential for a self-hosted endpoint, not a dead field.

Safety properties:
- ADDITIVE-NEUTRAL: no data is lost (both columns are NULL in every row); the ORM
  declaration and one serializer entry are dropped in the same commit.
- IDEMPOTENT: guarded on the column existing.
- REVERSIBLE: ``downgrade`` restores both columns as nullable; values were never
  stored, so nothing to restore.

Revision ID: 039_drop_dead_model_columns
Revises: 038_user_workspace_path
Create Date: 2026-10-26 00:00:00.000000
"""
from alembic import op
from sqlalchemy import text

revision = "039_drop_dead_model_columns"
down_revision = "038_user_workspace_path"
branch_labels = None
depends_on = None

TABLE = "models"
COLUMNS = ("api_model_name", "api_key")


def _columns(conn) -> set:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": TABLE},
    ).fetchall()
    return {r[0] for r in rows}


def _table_exists(conn) -> bool:
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return  # create_all-only install: the ORM model already omits them
    present = _columns(conn)
    for column in COLUMNS:
        if column in present:
            conn.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {column}"))


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    present = _columns(conn)
    for column in COLUMNS:
        if column not in present:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {column} VARCHAR"))
