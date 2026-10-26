"""Scope file records to a user (per-user workspace, Slice 2)

Why: files were global. `workspace_files.file_path` and `storage_objects.key` were
UNIQUE across the whole install, and nothing recorded who uploaded or generated a
row, so two people shared one namespace and the app could not answer "whose file is
this?" even in principle.

This migration adds the owner and makes uniqueness per-owner. It does NOT move any
bytes: the physical tree is relocated by `scripts/adopt_user_workspaces.py`, which
runs after the schema is in place and is dry-run by default.

Scope decisions (2026-10-26):
- Layout is user-first: `<workspace root>/users/<user id>/<vault>/...`.
- Existing records are adopted by the **first admin** (`owner_id` backfilled), because
  the person who ran this install owns what it produced.
- Knowledge stays shared by product decision, so `context_documents` gets no owner.

`owner_id` is nullable on purpose: rows written with no accounts at all (a fresh
clone, the test suite) stay unowned, and NULLs compare as distinct in a Postgres
unique index, so an unowned install behaves exactly as before.

Revision ID: 034_owner_scoped_files
Revises: 033_add_auth_sessions
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '034_owner_scoped_files'
down_revision = '033_add_auth_sessions'
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    return conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar() is not None


def _has_constraint(conn, name: str) -> bool:
    return conn.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = :n"
    ), {"n": name}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── workspace_files ─────────────────────────────────────────────────────
    if not _has_column(conn, 'workspace_files', 'owner_id'):
        op.add_column('workspace_files', sa.Column('owner_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'workspace_files_owner_id_fkey', 'workspace_files', 'users',
            ['owner_id'], ['id'], ondelete='SET NULL',
        )
        op.create_index('ix_workspace_files_owner_id', 'workspace_files', ['owner_id'])

    # Global uniqueness blocked two users from having a file at the same relative
    # path. Uniqueness belongs to the pair now.
    if _has_constraint(conn, 'workspace_files_file_path_key'):
        op.drop_constraint('workspace_files_file_path_key', 'workspace_files', type_='unique')
    if not _has_constraint(conn, 'workspace_files_owner_path_key'):
        op.create_unique_constraint(
            'workspace_files_owner_path_key', 'workspace_files', ['owner_id', 'file_path']
        )

    # ── storage_objects ─────────────────────────────────────────────────────
    if not _has_column(conn, 'storage_objects', 'owner_id'):
        op.add_column('storage_objects', sa.Column('owner_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'storage_objects_owner_id_fkey', 'storage_objects', 'users',
            ['owner_id'], ['id'], ondelete='SET NULL',
        )
        op.create_index('ix_storage_objects_owner_id', 'storage_objects', ['owner_id'])

    if _has_constraint(conn, 'storage_objects_key_key'):
        op.drop_constraint('storage_objects_key_key', 'storage_objects', type_='unique')
    if not _has_constraint(conn, 'storage_objects_owner_key_key'):
        op.create_unique_constraint(
            'storage_objects_owner_key_key', 'storage_objects', ['owner_id', 'key']
        )

    # ── adoption: everything that exists belongs to the first admin ─────────
    # Only when there is an admin to attribute it to. Rows that stay NULL are the
    # pre-accounts install case and keep behaving exactly as before.
    owner_id = conn.execute(sa.text(
        "SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id LIMIT 1"
    )).scalar()
    if owner_id is not None:
        for table in ('workspace_files', 'storage_objects'):
            conn.execute(sa.text(
                f"UPDATE {table} SET owner_id = :o WHERE owner_id IS NULL"
            ), {"o": owner_id})


def downgrade() -> None:
    conn = op.get_bind()

    for table, unique_name, global_name, column in (
        ('workspace_files', 'workspace_files_owner_path_key',
         'workspace_files_file_path_key', 'file_path'),
        ('storage_objects', 'storage_objects_owner_key_key',
         'storage_objects_key_key', 'key'),
    ):
        if _has_constraint(conn, unique_name):
            op.drop_constraint(unique_name, table, type_='unique')
        # The global constraint can only be restored if the data allows it; say so
        # rather than failing halfway through a rollback.
        try:
            op.create_unique_constraint(global_name, table, [column])
        except Exception as exc:  # noqa: BLE001
            print(f"could not restore {global_name}: {exc}")

        if _has_column(conn, table, 'owner_id'):
            op.drop_index(f'ix_{table}_owner_id', table_name=table)
            op.drop_constraint(f'{table}_owner_id_fkey', table, type_='foreignkey')
            op.drop_column(table, 'owner_id')
