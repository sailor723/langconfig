"""Add the users table (multi-user identities)

Why: the LAN gate could only prove "somebody knows the shared password". This
table makes each request attributable to a person and adds the (deliberately
minimal) role split — admin manages accounts and later publishes shared assets,
member only manages their own account.

Scope: identities, not isolation. No ``tenant_id``, and nothing is filtered by
``user_id`` in this migration — those columns are added where they already
exist (chat_sessions, audit_logs) in a later step of the same slice.

Idempotence: ``init_db()`` (create_all) runs before alembic on a fresh install
and has already created this table, in which case seed_all stamps instead of
upgrading. This upgrade can still meet an existing table when someone replays
the chain on a database whose schema came from the ORM first, so both the type
and the table are created only if absent — same guard style as 003.

Revision ID: 032_add_users
Revises: 031_chat_session_title
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '032_add_users'
down_revision = '031_chat_session_title'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # The enum type must exist before the table that references it. Guarded
    # because create_all() creates it under the same name.
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_type WHERE typname = 'userrole'"
    ))
    if result.scalar() is None:
        conn.execute(sa.text("CREATE TYPE userrole AS ENUM ('admin', 'member')"))

    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'users'"
    ))
    if result.scalar() is None:
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(length=64), nullable=False),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('display_name', sa.String(length=128), nullable=True),
            sa.Column('role',
                      postgresql.ENUM('admin', 'member', name='userrole',
                                      create_type=False),
                      nullable=False, server_default='member'),
            sa.Column('is_active', sa.Boolean(), nullable=False,
                      server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('now()')),
            sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('username', name='users_username_key'),
        )

    for index_name, column in (("ix_users_id", "id"), ("ix_users_username", "username")):
        result = conn.execute(sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :n"
        ), {"n": index_name})
        if result.scalar() is None:
            op.create_index(index_name, 'users', [column])


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_username"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS users"))
    op.execute(sa.text("DROP TYPE IF EXISTS userrole"))
