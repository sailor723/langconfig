"""Give every conversation a person (Slice 3, step 1)

`chat_sessions.user_id` has existed since the first schema and was never populated:
of 292 sessions, exactly one carried a value. `conversation_archives` and
`user_profiles` copy that column from the session, so they were empty in the same way.
The effect was the biggest remaining hole in the per-user story — files were private,
conversations were not.

This migration backfills every NULL to the first admin, the same rule the file records
followed in 034: the person who ran the install owns what it produced. New rows get
their author from the request identity (see api/chat/session.py).

Also adds the indexes the read paths need now that they filter on the column, and —
importantly — an index the UI was missing for a long time: the session list orders by
`updated_at`, which was unindexed with 292 rows.

Revision ID: 035_conversation_ownership
Revises: 034_owner_scoped_files
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = '035_conversation_ownership'
down_revision = '034_owner_scoped_files'
branch_labels = None
depends_on = None


def _has_index(conn, name: str) -> bool:
    return conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :n"
    ), {"n": name}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    owner_id = conn.execute(sa.text(
        "SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id LIMIT 1"
    )).scalar()

    if owner_id is not None:
        for table in ('chat_sessions', 'conversation_archives', 'user_profiles'):
            result = conn.execute(sa.text(
                f"UPDATE {table} SET user_id = :o WHERE user_id IS NULL"
            ), {"o": owner_id})
            print(f"  {table}: {result.rowcount} row(s) adopted by user {owner_id}")

    for name, table, columns in (
        ("ix_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"]),
        ("ix_chat_sessions_updated_at", "chat_sessions", ["updated_at"]),
        ("ix_conversation_archives_user_id", "conversation_archives", ["user_id"]),
        ("ix_user_profiles_user_id", "user_profiles", ["user_id"]),
    ):
        if not _has_index(conn, name):
            op.create_index(name, table, columns)


def downgrade() -> None:
    conn = op.get_bind()
    # The backfill is not undone: we cannot tell which rows were NULL before, and
    # putting them back to NULL would only re-open the hole this migration closed.
    for name in (
        "ix_chat_sessions_user_updated",
        "ix_chat_sessions_updated_at",
        "ix_conversation_archives_user_id",
        "ix_user_profiles_user_id",
    ):
        if _has_index(conn, name):
            op.drop_index(name)
