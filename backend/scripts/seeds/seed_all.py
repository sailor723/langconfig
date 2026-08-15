"""
One-shot database bootstrap + data reload for a fresh LangConfig install.
All seed assets (scripts + dumps) live in this folder: backend/scripts/seeds/.

Run from backend/:
    uv run python scripts/seeds/seed_all.py            # idempotent, safe to re-run
    uv run python scripts/seeds/seed_all.py --replace  # force-reload agents/tools from dumps

What it does (every step is idempotent):
    1. init_server()            -> create the PostgreSQL role + database if missing
    2. init_db()                -> create all 50 tables + pgvector extension
    3. alembic stamp head       -> record the migration version (no replay needed)
    4. seed_settings.py         -> default settings documents (models/general/etc.)
    5. seed_models.py           -> 28 cloud LLM providers (models table)
    6. seed_search_providers.py -> 6 search backends
    7. custom_tools_dump.sql    -> 53 tools incl. your 10 custom ones (restore if empty;
                                   otherwise seed_builtin_tools keeps the 43 built-ins in sync)
    8. deep_agents_dump.sql     -> 42 deep agents incl. your custom ones (restore if empty
                                   or under-populated — fewer rows than the dump)
    9. skills FS -> DB sync     -> upsert all SKILL.md files from backend/skills/ (33 total)
   10. chinook (best-effort)    -> create the sample DB + restore 11 tables for Graph Studio

No full DB dump is needed: the role/database are created fresh by step 1 and only
data-only dumps are reloaded, so machine-specific state (API keys, local models,
settings, chat history) never leaks into the bundle.

The startup sync in main.py also runs skills FS -> DB on every backend start; step 8
just makes the bootstrap self-contained so the data is in Postgres immediately.
local_models + API keys stay per-machine (.env / Settings).

--replace truncates deep_agent_templates and custom_tools before restoring the dumps
(resets them to Mac's exact state; only use when you want that, e.g. after the built-in
seed polluted the ids).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
SEEDS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text
from sqlalchemy.engine import make_url

from db.database import SessionLocal, engine, init_db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _db_url(dbname: str | None = None) -> str:
    """Render the configured DATABASE_URL, optionally swapping the database name."""
    url = make_url(engine.url.render_as_string(hide_password=False))
    if dbname:
        url = url.set(database=dbname)
    return url.render_as_string(hide_password=False)


def _run_python(args: list[str], env_extra: dict[str, str] | None = None) -> None:
    """Run a sibling script with the same interpreter (uv venv python)."""
    env = dict(os.environ)
    env.update(env_extra or {})
    subprocess.run([sys.executable, *args], cwd=str(BACKEND_DIR), env=env, check=True)


def _psql(sql: str, dbname: str | None = None) -> str:
    """Run a single psql statement, returning its trimmed stdout."""
    out = subprocess.run(
        ["psql", _db_url(dbname), "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _restore_dump(dump_name: str, dbname: str | None = None) -> None:
    """Load a data-only pg_dump file via psql (ON_ERROR_STOP so failures surface).

    PGOPTIONS applies a 10s lock_timeout so a restore that collides with the
    running backend fails fast instead of blocking indefinitely.
    """
    dump_path = SEEDS_DIR / dump_name
    print(f"  -> loading {dump_path.name} ...")
    subprocess.run(
        ["psql", _db_url(dbname), "-q", "-v", "ON_ERROR_STOP=1", "-f", str(dump_path)],
        check=True,
        env={**os.environ, "PGOPTIONS": "-c lock_timeout=10s"},
    )


def _dump_row_count(dump_name: str) -> int:
    """Count data rows inside a pg_dump data-only COPY block.

    Used to decide whether a table is under-populated (partial/seed-only data)
    and should be reloaded from the canonical dump on a fresh bootstrap.
    """
    count = 0
    in_copy = False
    with (SEEDS_DIR / dump_name).open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("COPY ") and "FROM stdin" in line:
                in_copy = True
            elif in_copy and line.rstrip("\n") == "\\.":
                break
            elif in_copy:
                count += 1
    return count


def _admin_run(sql: str) -> str | None:
    """Run a statement as a superuser (to create role/db); returns trimmed stdout.

    Host/port come from the configured DATABASE_URL, so this targets whichever
    server the app uses (native or docker) — no per-mode code changes.
    Tries in order:
      1. app-user psql against the `postgres` maintenance DB (works where the app
         role is superuser, or auth is trust/md5)
      2. ``sudo -n -u postgres psql`` (works on WSL/Linux with passwordless sudo +
         peer auth)
    Returns None if both fail — the caller then prints manual instructions.
    """
    url = make_url(engine.url.render_as_string(hide_password=False))
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    user = url.username or "langconfig"
    host_args = ["-h", url.host or "localhost"]
    if url.port:
        host_args += ["-p", str(url.port)]
    candidates = [
        ["psql", *host_args, "-d", "postgres", "-U", user, "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
        ["sudo", "-n", "-u", "postgres", "psql", "-d", "postgres", "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
    ]
    for cmd in candidates:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, env=env, check=True)
            return out.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def _truncate(table: str) -> None:
    """Wipe a table and restart its identity (CASCADE covers referencing rows).

    A running backend can hold locks on these tables (idle-in-transaction
    pool connections), so a lock_timeout makes that fail fast with a clear
    error instead of hanging on TRUNCATE forever.
    """
    print(f"  -> truncating {table} (--replace)")
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


def _table_count(table: str) -> int:
    with SessionLocal() as db:
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def step_init_server() -> None:
    """Create the PostgreSQL role + database if they don't exist (idempotent)."""
    print("\n[1/10] init_server  (create role + database if missing)")
    url = make_url(engine.url.render_as_string(hide_password=False))
    user = url.username or "langconfig"
    dbname = url.database or "langconfig"
    password = (url.password or "").replace("'", "''")
    if not password:
        print("  ! DATABASE_URL has no password; cannot auto-create the role.")
        print("    Create the role/database manually, then re-run this script.")
        return

    if _admin_run("SELECT 1") is None:
        print("  ! Cannot connect as a superuser to create role/database.")
        print("    Run these once as the postgres superuser, then re-run this script:")
        print(f'    sudo -u postgres psql -c "CREATE ROLE {user} LOGIN PASSWORD \'{password}\' CREATEDB;"')
        print(f'    sudo -u postgres psql -c "CREATE DATABASE {dbname} OWNER {user};"')
        return

    if _admin_run(f"SELECT 1 FROM pg_roles WHERE rolname = '{user}'") == "1":
        print(f"  -> role '{user}' already exists")
    else:
        print(f"  -> creating role '{user}'")
        _admin_run(f"CREATE ROLE {user} LOGIN PASSWORD '{password}' CREATEDB")

    if _admin_run(f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'") == "1":
        print(f"  -> database '{dbname}' already exists")
    else:
        print(f"  -> creating database '{dbname}'")
        _admin_run(f"CREATE DATABASE {dbname} OWNER {user}")


def step_init_db() -> None:
    print("\n[2/10] init_db()  (tables + pgvector)")
    init_db()


def step_stamp_head() -> None:
    print("\n[3/10] alembic stamp head")
    # Fresh DBs cannot replay the 001..021 migration chain; stamping records the
    # version so future alembic operations (e.g. `alembic upgrade head`) work.
    subprocess.run([sys.executable, "-m", "alembic", "stamp", "head"], cwd=str(BACKEND_DIR), check=True)


def step_settings() -> None:
    print("\n[4/10] seed_settings.py  (default settings documents)")
    _run_python(["scripts/seeds/seed_settings.py"])


def step_models() -> None:
    print("\n[5/10] seed_models.py  (28 cloud providers)")
    _run_python(["scripts/seeds/seed_models.py"], {"MODELS_CSV": str(SEEDS_DIR / "models_seed.csv")})


def step_search_providers() -> None:
    print("\n[6/10] seed_search_providers.py  (6 search backends)")
    _run_python(["scripts/seeds/seed_search_providers.py"])


def step_custom_tools(replace: bool) -> None:
    print("\n[7/10] custom_tools  (53 tools incl. custom)")
    count = _table_count("custom_tools")
    if count == 0 or replace:
        if replace and count:
            _truncate("custom_tools")
        _restore_dump("custom_tools_dump.sql")
    else:
        print(f"  -> custom_tools already has {count} row(s); running seed_builtin_tools to sync built-ins")
        _run_python(["scripts/seeds/seed_builtin_tools.py"])


def step_deep_agents(replace: bool) -> None:
    print("\n[8/10] deep_agents  (42 agents incl. custom)")
    count = _table_count("deep_agent_templates")
    dump_count = _dump_row_count("deep_agents_dump.sql")
    if count == 0 or replace:
        if replace and count:
            _truncate("deep_agent_templates")
        _restore_dump("deep_agents_dump.sql")
        return

    if count < dump_count:
        # Under-populated table (stray rows from a partial run or an older
        # install) — reload the canonical agent set so a fresh bootstrap always
        # ends up complete instead of silently skipping the dump.
        print(f"  -> table has {count} row(s), fewer than the dump's {dump_count}; reloading full agent set")
        _truncate("deep_agent_templates")
        _restore_dump("deep_agents_dump.sql")
        return

    print("  -> already has user agents; skipping dump (re-run with --replace to reset)")


def step_skills() -> None:
    """Sync SKILL.md files from backend/skills/ into the skills table (FS -> DB).

    Scans BOTH roots: the builtin folder (15 skills) and the personal root
    (18 skills at backend/skills/<id>/). The app's startup sync only scans the
    builtin folder, so this step is what makes personal skills appear on a fresh
    install. Mirrors the startup mtime-based upsert (never deletes).
    """
    print("\n[9/10] skills  (FS -> DB sync)")
    from datetime import datetime, timezone

    from core.skills.sync import (
        scan_builtin_skills,
        fs_to_db_dict,
        derive_source_type,
        PERSONAL_SKILLS_ROOT,
    )
    from models.skill import Skill as SkillModel

    # builtin/ first, then personal root (skip the builtin subfolder so each
    # SKILL.md is visited exactly once).
    seen: set = set()
    skill_mds: list = list(scan_builtin_skills())
    for md in PERSONAL_SKILLS_ROOT.rglob("SKILL.md"):
        if "builtin" in md.parts or md in seen:
            continue
        skill_mds.append(md)

    synced = 0
    with SessionLocal() as db:
        for skill_md in skill_mds:
            data = fs_to_db_dict(skill_md)
            data["source_type"] = derive_source_type(skill_md)
            existing = db.query(SkillModel).filter(SkillModel.skill_id == data["skill_id"]).first()
            if existing:
                # Only overwrite when the filesystem copy is newer than the DB row.
                fs_mtime = data.get("file_modified_at")
                if fs_mtime and (not existing.file_modified_at or fs_mtime > existing.file_modified_at):
                    for key, value in data.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    existing.indexed_at = datetime.now(timezone.utc)
                    synced += 1
            else:
                data["indexed_at"] = datetime.now(timezone.utc)
                db.add(SkillModel(**data))
                synced += 1
        db.commit()
    print(f"  -> {synced} skill(s) synced (total in DB: {_table_count('skills')})")


def step_chinook() -> None:
    print("\n[10/10] chinook sample DB (Graph Studio SQL agent, best-effort)")
    try:
        owner = make_url(engine.url.render_as_string(hide_password=False)).username or "langconfig"
        if _psql("SELECT 1 FROM pg_database WHERE datname='chinook'", dbname="postgres") != "1":
            print("  -> creating database 'chinook'")
            _psql(f"CREATE DATABASE chinook OWNER {owner}", dbname="postgres")
        n = _psql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'", dbname="chinook")
        if n == "0":
            _restore_dump("chinook_dump.sql", dbname="chinook")
        else:
            print(f"  -> chinook already has {n} tables; skipping")
    except Exception as exc:  # noqa: BLE001 - never block the main bootstrap on chinook
        print(f"  ! chinook setup skipped: {exc}")


def summary() -> None:
    print("\n=== Summary ===")
    for table, label in (
        ("models", "LLM providers"),
        ("search_providers", "search backends"),
        ("custom_tools", "tools"),
        ("deep_agent_templates", "deep agents"),
        ("skills", "skills"),
    ):
        print(f"  {label:<20} {_table_count(table)}")
    print("  local_models/API keys  configured per-machine in the Settings UI (DB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot LangConfig DB bootstrap + data reload")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="TRUNCATE deep_agent_templates + custom_tools before restoring Mac dumps",
    )
    args = parser.parse_args()

    print("LangConfig DB seed-all bootstrap")
    step_init_server()
    step_init_db()
    step_stamp_head()
    step_settings()
    step_models()
    step_search_providers()
    step_custom_tools(replace=args.replace)
    step_deep_agents(replace=args.replace)
    step_skills()
    step_chinook()
    summary()
    print("\nDone. Start the backend (uv run python main.py), then the frontend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
