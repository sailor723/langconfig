"""settings_documents per account — key becomes (user_id, ns)

Migration 028 created ``settings_documents`` with one row per namespace: a
single site-wide document, which meant every account on the instance shared one
set of provider credentials. Migration 037 makes the row per account, so each
user stores their own LLM keys, web-search keys and model defaults.

Shape:

    before:  settings_documents( ns PK, document, revision, updated_at )
    after:   settings_documents( user_id PK, ns PK, document, revision, updated_at )

``user_id`` defaults to 1 (the owner), so:

- every existing row becomes the owner's row without a data rewrite;
- the owner's row doubles as the **shared** layer that other accounts inherit
  field by field (``core/settings/store.get_effective_document``), which is what
  keeps an install usable the moment a second account is created;
- any code path that does not pass an account still works, unchanged.

Safety properties:
- ADDITIVE on data: no row is deleted, no document is rewritten. Only the key
  changes, and the default fills the new column.
- IDEMPOTENT: guarded on the current shape, so re-running is a no-op and it also
  copes with a database booted via ``create_all`` (table already correct).
- REVERSIBLE: ``downgrade`` restores the single-column primary key, refusing to
  run when more than one account has rows (that data cannot be represented by a
  one-row-per-namespace table — dropping it silently would be data loss).

Revision ID: 037_settings_per_user
Revises: 036_owner_scoped_skills
Create Date: 2026-10-26 00:00:00.000000
"""
from alembic import op
from sqlalchemy import text

revision = "037_settings_per_user"
down_revision = "036_owner_scoped_skills"
branch_labels = None
depends_on = None

TABLE = "settings_documents"


def _columns(conn) -> set:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": TABLE},
    ).fetchall()
    return {r[0] for r in rows}


def _pk_columns(conn) -> list:
    rows = conn.execute(
        text(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
            WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
            """
        ),
        {"t": TABLE},
    ).fetchall()
    return [r[0] for r in rows]


def _table_exists(conn) -> bool:
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": TABLE}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        # create_all-only installs create the table from the ORM model, which
        # already carries (user_id, ns). Nothing to migrate.
        return

    cols = _columns(conn)
    if "user_id" not in cols:
        conn.execute(
            text(
                f"ALTER TABLE {TABLE} "
                "ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
            )
        )
        # Existing rows are the pre-037 site-wide document → the owner's row,
        # which also becomes the shared layer other accounts inherit from.
        conn.execute(text(f"UPDATE {TABLE} SET user_id = 1 WHERE user_id IS NULL"))
        conn.execute(text(f"ALTER TABLE {TABLE} ALTER COLUMN user_id DROP DEFAULT"))

    # Compare as a set: PostgreSQL reports the key in attribute order, which is
    # (ns, user_id) after the ALTER — requiring the literal order would make this
    # migration drop and rebuild the primary key on every re-run.
    if set(_pk_columns(conn)) != {"user_id", "ns"}:
        # The old constraint has the conventional name; drop it by introspection
        # so a renamed constraint does not break the migration.
        for (name,) in conn.execute(
            text(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = CAST(:t AS regclass) AND contype = 'p'
                """
            ),
            {"t": TABLE},
        ).fetchall():
            conn.execute(text(f'ALTER TABLE {TABLE} DROP CONSTRAINT "{name}"'))
        conn.execute(text(f"ALTER TABLE {TABLE} ADD PRIMARY KEY (user_id, ns)"))

    # Lookup by namespace across accounts (admin tooling, "who has set a key").
    conn.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_settings_documents_ns "
            f"ON {TABLE} (ns)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn) or "user_id" not in _columns(conn):
        return

    accounts = conn.execute(
        text(f"SELECT count(DISTINCT user_id) FROM {TABLE}")
    ).scalar() or 0
    if accounts > 1:
        raise RuntimeError(
            f"{TABLE} holds rows for {accounts} accounts; a single-account table "
            "cannot represent them. Delete or export the extra accounts' settings "
            "before downgrading."
        )

    for (name,) in conn.execute(
        text(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = CAST(:t AS regclass) AND contype = 'p'
            """
        ),
        {"t": TABLE},
    ).fetchall():
        conn.execute(text(f'ALTER TABLE {TABLE} DROP CONSTRAINT "{name}"'))

    conn.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN user_id"))
    conn.execute(text(f"ALTER TABLE {TABLE} ADD PRIMARY KEY (ns)"))
    conn.execute(text("DROP INDEX IF EXISTS ix_settings_documents_ns"))
