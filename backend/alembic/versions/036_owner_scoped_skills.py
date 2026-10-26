"""Scope personal skills to a user

Personal skills were shared by construction: one `backend/skills/personal/` folder for
everybody, and a `skills` table with no owner column — so any account could see, edit and
delete any other account's skills, and the catalogue every agent received listed all of
them. This is the same cut the workspace got in 034, applied to the skill library.

Layout, decided with the product owner (2026-10-26): personal skills stay **in the
repository** so they remain git-tracked and travel with the team seed, but the tree gets
one folder per account — `backend/skills/personal/<user id>/<skill>/`. Built-ins stay
shared: they are the product's, not anybody's.

Backfill rule matches the file records: the first admin owns everything that already
existed, because the person who ran the install created it.

`skill_id` had no uniqueness constraint at all, so the composite UNIQUE below is new
rather than a replacement: two accounts may now hold the same skill id, which is the
point.

Revision ID: 036_owner_scoped_skills
Revises: 035_conversation_ownership
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = '036_owner_scoped_skills'
down_revision = '035_conversation_ownership'
branch_labels = None
depends_on = None


def _has_column(conn, table, column):
    return conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": column}).scalar() is not None


def _has_constraint(conn, name):
    return conn.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname=:n"), {"n": name}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, 'skills', 'owner_id'):
        op.add_column('skills', sa.Column('owner_id', sa.Integer(), nullable=True))
        op.create_foreign_key('skills_owner_id_fkey', 'skills', 'users',
                              ['owner_id'], ['id'], ondelete='SET NULL')
        op.create_index('ix_skills_owner_id', 'skills', ['owner_id'])

    # Two accounts may hold the same skill id; two rows for one account may not.
    if not _has_constraint(conn, 'skills_owner_skill_key'):
        op.create_unique_constraint('skills_owner_skill_key', 'skills',
                                    ['owner_id', 'skill_id'])

    owner = conn.execute(sa.text(
        "SELECT id FROM users WHERE role='admin' AND is_active ORDER BY id LIMIT 1"
    )).scalar()
    if owner is not None:
        result = conn.execute(sa.text(
            "UPDATE skills SET owner_id = :o WHERE source_type = 'personal' AND owner_id IS NULL"
        ), {"o": owner})
        print(f"  personal skills adopted by user {owner}: {result.rowcount}")
        # Built-ins stay unowned on purpose; a row that is neither builtin nor personal
        # (project skills) is owned by whoever installed it, so nothing is invisible.
        result = conn.execute(sa.text(
            "UPDATE skills SET owner_id = :o WHERE owner_id IS NULL AND source_type <> 'builtin'"
        ), {"o": owner})
        print(f"  other non-builtin skills adopted: {result.rowcount}")


def downgrade() -> None:
    conn = op.get_bind()
    if _has_constraint(conn, 'skills_owner_skill_key'):
        op.drop_constraint('skills_owner_skill_key', 'skills', type_='unique')
    if _has_column(conn, 'skills', 'owner_id'):
        op.drop_index('ix_skills_owner_id', table_name='skills')
        op.drop_constraint('skills_owner_id_fkey', 'skills', type_='foreignkey')
        op.drop_column('skills', 'owner_id')
