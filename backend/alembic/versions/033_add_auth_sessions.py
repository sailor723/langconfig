"""Add auth_sessions (sign-in cookies)

Why: a login panel cannot use HTTP Basic — a form cannot set the browser's
credential, and Basic has no session to revoke. This table is the server-side half
of a real session: one row per signed-in browser, addressed by the SHA-256 of an
opaque cookie value, with a sliding expiry.

The raw token is never stored, so a database dump cannot be replayed as a login.
Rows are deleted on sign-out and on expiry; `users.id` cascades, so an account
removed by hand does not leave live sessions behind.

Idempotence: like 032, `init_db()` (create_all) may already have created this on a
fresh install, and seed_all stamps instead of upgrading in that case. The guards
below keep a replayed chain from failing.

Revision ID: 033_add_auth_sessions
Revises: 032_add_users
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '033_add_auth_sessions'
down_revision = '032_add_users'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'auth_sessions'"
    ))
    if result.scalar() is None:
        op.create_table(
            'auth_sessions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('now()')),
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('now()')),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('user_agent', sa.String(length=300), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('token_hash', name='auth_sessions_token_hash_key'),
        )

    for index_name, columns in (
        ("ix_auth_sessions_id", ["id"]),
        ("ix_auth_sessions_token_hash", ["token_hash"]),
        ("ix_auth_sessions_user_id", ["user_id"]),
        ("ix_auth_sessions_expires_at", ["expires_at"]),
        ("ix_auth_sessions_user_expiry", ["user_id", "expires_at"]),
    ):
        result = conn.execute(sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :n"
        ), {"n": index_name})
        if result.scalar() is None:
            op.create_index(index_name, 'auth_sessions', columns)


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS auth_sessions"))
