"""users.workspace_path — an optional per-account workspace root

Until now a person's files always lived at ``<install root>/users/<id>/`` — derived
from the id by ``services/user_roots.py``, never stored. That is right for the normal
case and wrong whenever one account needs its files somewhere else: a second disk, an
encrypted volume, a big scratch mount, a machine-local path that must not be shared
with the rest of the install.

Adds one nullable column:

    users.workspace_path  VARCHAR(1024) NULL
        NULL  → keep the convention: ``<install root>/users/<id>``
        value → an absolute path, expanded and validated on write;
                everything for that account hangs off it exactly as before
                (``<path>/<vault>/agents/agent_<id>/…``)

The column is deliberately on ``users`` and not in ``settings_documents``: settings
are per account too, but a workspace root decides *where a person's data is*, which
has to be readable without a settings resolution (and before one, at boot).

Safety properties:
- ADDITIVE: one nullable column, no backfill, no rewrite. Every existing account
  keeps the derived path, so behaviour is unchanged until someone sets a value.
- REVERSIBLE: dropping the column loses only the overrides; the default layout is
  derived from the id and therefore rebuilds itself.
- UNIQUE-ISH by convention, not by constraint: two accounts pointing at the same
  directory is a misconfiguration the API refuses (``services/user_roots`` has to
  resolve a path to one owner), but a hard UNIQUE would also reject two NULLs on
  some engines — so the check lives at the API edge, with a warning in the log.

Revision ID: 038_user_workspace_path
Revises: 037_settings_per_user
Create Date: 2026-10-26 00:00:00.000000
"""
from alembic import op
from sqlalchemy import text

revision = "038_user_workspace_path"
down_revision = "037_settings_per_user"
branch_labels = None
depends_on = None

TABLE = "users"
COLUMN = "workspace_path"


def _has_column(conn) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": TABLE, "c": COLUMN},
    ).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is None:
        # create_all-only install: the ORM model already carries the column.
        return
    if _has_column(conn):
        return
    conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR(1024)"))


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn):
        return
    conn.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}"))
