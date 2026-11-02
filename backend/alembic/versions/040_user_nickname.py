"""users.nickname — a second, friendlier thing to type at the login prompt

``username`` is what the LAN gate's Basic prompt sends and what ownership columns
point at, so it has to stay stable and machine-shaped (``user7``). People type
their own name instead, and a 20-person training session is exactly where
"was I user7 or user9?" costs a minute per person.

Adds one nullable column plus a unique index:

    users.nickname  VARCHAR(32) NULL
        NULL  → no alias; the account signs in by ``username`` only
        value → an *additional* login identifier; ``username`` keeps working

Uniqueness is case-insensitive and lives in a partial index (``WHERE nickname IS
NOT NULL``), because PostgreSQL treats NULLs as distinct — a plain UNIQUE would
already allow many NULLs, but the partial index also says what we mean.

One rule cannot be expressed as a constraint and is enforced at the API edge
instead: a nickname may not equal *anybody's* username, and a new username may
not equal an existing nickname. Two identifiers for one person are fine; one
identifier resolving to two people is not.

Safety properties:
- ADDITIVE: one nullable column, no backfill. Every existing account keeps
  signing in exactly as before.
- REVERSIBLE: dropping the column removes the aliases and nothing else.
- The case-insensitive index is built with ``lower(nickname)``, so ``Alice`` and
  ``alice`` cannot both be claimed — the browser prompt does not preserve the
  case people intend.

Revision ID: 040_user_nickname
Revises: 039_drop_dead_model_columns
Create Date: 2026-11-02 00:00:00.000000
"""
from alembic import op
from sqlalchemy import text

revision = "040_user_nickname"
down_revision = "039_drop_dead_model_columns"
branch_labels = None
depends_on = None

TABLE = "users"
COLUMN = "nickname"
INDEX = "ix_users_nickname_lower"


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
        # create_all-only install: the ORM model already carries the column, and
        # the index is created by the model's Index definition.
        return
    if not _has_column(conn):
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR(32)"))
    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} "
            f"ON {TABLE} (lower({COLUMN})) WHERE {COLUMN} IS NOT NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(f"DROP INDEX IF EXISTS {INDEX}"))
    if _has_column(conn):
        conn.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}"))
