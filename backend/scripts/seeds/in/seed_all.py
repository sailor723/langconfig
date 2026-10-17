"""
One-shot database bootstrap + data reload for a fresh LangConfig install.
All seed assets live in this folder, split by role:

    backend/scripts/seeds/
    ├── _seedpaths.py   the one place that knows this layout (imported by all)
    ├── in/             THIS FILE + the artifacts it loads + their loaders
    ├── out/            exporters: live DB -> committable artifact
    └── verify/         tests, a report, and the two-machine rehearsal

Run from backend/:
    uv run python scripts/seeds/in/seed_all.py            # idempotent, safe to re-run
    uv run python scripts/seeds/in/seed_all.py --replace  # destructive reset to the baseline

What it does (every step is idempotent):
    1. init_server()            -> create the PostgreSQL role + database if missing
    2. init_db()                -> create all 48 tables + pgvector extension
    3. alembic stamp head       -> record the migration version (no replay needed)
    4. seed_settings.py         -> default settings documents (missing namespaces)
    4b. settings_seed.json      -> the TEAM's settings, three-way merged so a key
                                   somebody changed locally is never overwritten
    5. seed_models.py + upsert  -> model catalog incl. the vision model
    6. seed_search_providers.py -> 6 search backends
    7. custom_tools_dump.sql    -> tools (restore if empty)
       + custom_tools_merge.sql -> tools, ADDITIVE union on tool_id: inserts only
                                   the ids that are absent, never rewrites a row
       + seed_builtin_tools / read_any_file -> built-ins, but only the MISSING ones:
                                   seed_builtin_tools leaves every existing row alone
                                   (its --refresh flag is the only way to overwrite,
                                   and this script never passes it), while
                                   seed_read_any_file_tool upserts its own row in place
    8. deep_agents_merge.sql    -> agents, ADDITIVE: inserts only names that are
                                   absent, never removes or rewrites an existing agent
    9. skills FS -> DB sync     -> upsert every SKILL.md under backend/skills/
                                   (builtin/, personal/ and the top-level <id>/ dirs);
                                   an invalid dir is reported and skipped
   10. chinook (best-effort)    -> create the sample DB + restore 11 tables for Graph Studio

No full DB dump is needed: the role/database are created fresh by step 1 and only
data-only dumps are reloaded, so machine-specific state (API keys, local models,
settings, chat history) never leaks into the bundle.

The startup sync in main.py also runs skills FS -> DB on every backend start; step 9
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

# One level deeper than it used to be, so the layout comes from _seedpaths
# instead of counting directories from __file__.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _seedpaths import BACKEND as BACKEND_DIR, IN_DIR, SEEDS as SEEDS_DIR  # noqa: E402

from sqlalchemy import text
from sqlalchemy import text as sa_text
from sqlalchemy.engine import make_url

from db.database import SessionLocal, engine, init_db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Agent ids inserted by step 8 in this run; step 8.5 re-bakes only these.
_SEEDED_AGENT_IDS: set[int] = set()


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
    dump_path = IN_DIR / dump_name
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
    with (IN_DIR / dump_name).open(encoding="utf-8", errors="replace") as fh:
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


def _alembic_version() -> str | None:
    """The revision this database records, or None when it has none.

    None means "fresh": no alembic_version table, or an empty one. That is the
    only fact needed to tell a first install from an update, so the script does
    not need the operator to declare which it is.
    """
    # Deliberately NOT via the psql binary: a machine without it would either
    # raise FileNotFoundError or, worse, return None here and be mistaken for a
    # fresh database — which is the silent schema-drift this function exists to
    # prevent. SQLAlchemy is already a hard dependency of the seed.
    try:
        with engine.connect() as conn:
            exists = conn.execute(sa_text(
                "SELECT to_regclass('public.alembic_version') IS NOT NULL"
            )).scalar()
            if not exists:
                return None
            row = conn.execute(sa_text(
                "SELECT version_num FROM alembic_version LIMIT 1"
            )).scalar()
            return (row or None)
    except Exception as exc:                      # noqa: BLE001
        # Cannot tell => say so loudly rather than guessing "fresh", because the
        # guess would stamp a database whose migrations never ran.
        raise SystemExit(
            f"cannot read alembic_version ({type(exc).__name__}: {exc}).\n"
            "  Refusing to guess between 'fresh database' and 'needs upgrade' — "
            "getting that wrong leaves the schema silently behind the code.\n"
            "  Check DATABASE_URL / the PostgreSQL server, then re-run."
        )


def step_schema_version() -> None:
    """[3/10] record the schema version (fresh) or apply pending migrations (update).

    Why this cannot be one unconditional command: ``init_db()`` created the
    schema from the ORM models, and the 001..0xx chain cannot be replayed on top
    of it, so a FRESH database must be *stamped* — recorded at head without
    running anything. An EXISTING database must not be stamped: that would mark
    pending migrations applied without ever running them, leaving the schema
    behind the code with no error to show for it. ``upgrade head`` is a no-op
    when the database is already at head, so it is safe on both.

    There is no flag for this on purpose: the database itself says which case it
    is. Forcing ``upgrade`` on a fresh database would collide with the tables
    ``init_db()`` has just created, so the only honest override would be the
    dangerous one.
    """
    current = _alembic_version()

    if current is None:
        print("\n[3/10] alembic stamp head  (fresh database: schema just created)")
        subprocess.run([sys.executable, "-m", "alembic", "stamp", "head"],
                       cwd=str(BACKEND_DIR), check=True)
        return

    print(f"\n[3/10] alembic upgrade head  (existing database, currently at {current})")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=str(BACKEND_DIR), check=True)


def step_settings() -> None:
    print("\n[4/10] seed_settings.py  (default settings documents)")
    _run_python(["scripts/seeds/in/seed_settings.py"])


def step_team_settings() -> None:
    """[4b] Apply the exported team settings over the code defaults.

    seed_settings.py above only fills namespaces that are EMPTY, so a value
    changed in the UI never reached anyone. This applies settings_seed.json with
    a three-way merge (core/settings/team_seed.py): untouched keys adopt the team
    value, keys somebody changed themselves are left alone.
    """
    print("\n[4b/10] team settings  (three-way merge over the defaults)")
    from core.settings.team_seed import apply_team_seed

    result = apply_team_seed()
    if not result["present"]:
        print("  -> settings_seed.json missing; regenerate with "
              "scripts/seeds/out/export_settings.py")
        return
    print(f"  -> {result['written']} document(s) updated, "
          f"{len(result['applied'])} key(s) taken from the team seed, "
          f"{len(result['kept'])} left as they are (changed locally)")
    if result["kept"]:
        print(f"     kept: {', '.join(result['kept'][:6])}"
              + (" …" if len(result["kept"]) > 6 else ""))
    skipped = result.get("unreadable") or []
    if skipped:
        print(f"  !! skipped {len(skipped)} namespace(s) with a secret this machine cannot "
              f"decrypt: {', '.join(skipped)}")
        print("     Their stored values are untouched; only the team merge was skipped.")
        print("     Fix with:  .venv/bin/python scripts/audit_settings_secrets.py --rekey-from "
              "<the key that wrote them>")
        print("     This no longer aborts the seed, but those settings are not applied.")


def step_models() -> None:
    print("\n[5/10] models  (catalog + per-model capabilities)")
    _run_python(["scripts/seeds/in/seed_models.py"], {"MODELS_CSV": str(IN_DIR / "models_seed.csv")})
    # seed_models.py derives capabilities from a PER-PROVIDER table, in which
    # `deepseek` has no vision flag, and models_seed.csv has no row for
    # deepseek-flash at all — so the vision model the agent editor lists
    # (capabilities.vision) and the reader pins per agent (d42f1a9) simply did
    # not exist on a fresh install. upsert_model.py carries that row's real
    # capabilities; it is idempotent and only touches `models`.
    print("  -> upsert_model.py --preset deepseek-flash (vision model)")
    _run_python(["scripts/seeds/in/upsert_model.py", "--preset", "deepseek-flash"])


def step_search_providers() -> None:
    print("\n[6/10] seed_search_providers.py  (6 search backends)")
    _run_python(["scripts/seeds/in/seed_search_providers.py"])


def step_custom_tools(replace: bool) -> None:
    print("\n[7/10] custom_tools  (restore-if-empty, then additive merge)")
    count = _table_count("custom_tools")
    if count == 0 or replace:
        if replace and count:
            _truncate("custom_tools")
        # The merge below runs unconditionally, so --replace still ends at the
        # full tool count: the dump supplies explicit ids, the merge fills gaps.
        _restore_dump("custom_tools_dump.sql")
    else:
        print(f"  -> custom_tools already has {count} row(s); running seed_builtin_tools to sync built-ins")
        _run_python(["scripts/seeds/in/seed_builtin_tools.py"])

    # Additive catalog merge. The dump above carries explicit ids and was only
    # applied to an EMPTY table, so a teammate who had made their own tools
    # received none of the shared catalog. This file unions by tool_id: their
    # rows stay exactly as they are, missing ones are added with ids from the
    # sequence. (Their 5 tools + 3 of yours they lack = 8.)
    if (IN_DIR / "custom_tools_merge.sql").exists():
        before = _table_count("custom_tools")
        print("  -> custom_tools_merge.sql (additive; existing tool_ids untouched)")
        _restore_dump("custom_tools_merge.sql")
        print(f"  -> {_table_count('custom_tools') - before} tool(s) added, "
              f"{before} pre-existing left untouched")
    else:
        print("  -> custom_tools_merge.sql missing; regenerate with "
              "scripts/seeds/out/export_tools_merge.py")

    # read_any_file is a BUILTIN whose definition lives in its own script (it
    # needs trusted code — filesystem, tesseract, the reader graph — so it is
    # not a UI tool). Nothing used to call that script, so a fresh install came
    # up without the tool the vision/reader path depends on. Idempotent: it
    # updates the row in place.
    print("  -> seed_read_any_file_tool.py (builtin reader tool)")
    _run_python(["scripts/seeds/in/seed_read_any_file_tool.py"])


def step_deep_agents(replace: bool) -> None:
    """[8] agents — additive by default: never removes or rewrites a row.

    This used to restore ``deep_agents_dump.sql`` (explicit ids) after a
    ``TRUNCATE deep_agent_templates RESTART IDENTITY CASCADE`` whenever the table
    held FEWER rows than the dump. That condition is met by exactly the people
    who must not be affected — a teammate who created their own three agents
    has three rows, so the seed deleted them, and the CASCADE took their
    ``chat_sessions`` with it (``agent_id`` is a foreign key).

    The default path now applies ``deep_agents_merge.sql``: one INSERT per agent,
    without an ``id`` (the target sequence assigns it, so no collision with the
    target's own rows) and guarded by ``WHERE NOT EXISTS (… name = …)`` so an
    agent whose name is already present — the teammate's own version included —
    is left exactly as it is. Idempotent: re-running inserts nothing.

    ``--replace`` still resets, because a destructive reset is occasionally what
    someone wants — it truncates, so it says so first. It then restores the merge
    file, so the reset lands exactly on the maintained baseline. It used to
    restore ``deep_agents_dump.sql``, which is now older than the merge and
    would have installed a smaller, partly-retired catalogue.
    """
    print("\n[8/10] agents  (additive merge; existing agents are never touched)")
    count = _table_count("deep_agent_templates")

    if replace:
        if count:
            print(f"  !! --replace: TRUNCATE deep_agent_templates CASCADE removes the "
                  f"{count} existing agent(s) AND their chat sessions")
            _truncate("deep_agent_templates")
        # Reset from the MERGE file, not the explicit-id dump. The dump is an
        # older snapshot (44 agents vs the merge's 56) AND it carries two agents
        # that have since been retired, so restoring it alone installs less than
        # the default path while restoring it *and* the merge installs more (58:
        # the union, retired rows included). A reset should land exactly on the
        # maintained baseline, which is the merge file — and only that.
        if not (IN_DIR / "deep_agents_merge.sql").exists():
            print("  -> deep_agents_merge.sql missing; cannot reset without it "
                  "(regenerate with scripts/seeds/out/export_agents_merge.py)")
            return
        _restore_dump("deep_agents_merge.sql")
        # A reset replaces every agent, so identity applies to all of them.
        with SessionLocal() as db:
            _SEEDED_AGENT_IDS.clear()
            _SEEDED_AGENT_IDS.update(
                r[0] for r in db.execute(sa_text("SELECT id FROM deep_agent_templates")))
        print(f"  -> reset to the baseline ({_table_count('deep_agent_templates')} agent(s))")
        return

    if not (IN_DIR / "deep_agents_merge.sql").exists():
        print("  -> deep_agents_merge.sql missing; regenerate it with "
              "scripts/seeds/out/export_agents_merge.py")
        return

    # Remember which names existed so the identity backfill can be limited to
    # the agents THIS run inserted. Without that it rewrote every agent in the
    # database — a teammate's own included — baking this machine's workspace
    # into prompts and docs that were not ours to touch.
    with SessionLocal() as db:
        names_before = {r[0] for r in db.execute(sa_text(
            "SELECT name FROM deep_agent_templates"))}

    before = count
    _restore_dump("deep_agents_merge.sql")
    after = _table_count("deep_agent_templates")
    print(f"  -> {after - before} agent(s) added, {before} pre-existing left untouched "
          f"({after} total)")

    # Rows whose name was not present before the merge are exactly what this run
    # inserted — the merge only ever adds, and only for absent names.
    with SessionLocal() as db:
        newly = [r[0] for r in db.execute(sa_text(
            "SELECT id, name FROM deep_agent_templates")) if r[1] not in names_before]
    _SEEDED_AGENT_IDS.clear()
    _SEEDED_AGENT_IDS.update(newly)
    print(f"  -> identity backfill limited to the {len(newly)} agent(s) just added")


def step_identity() -> None:
    """[8.5] Bake real agent identity (id + workspace + AGENTS.md/CLAUDE.md).

    The deep_agents dump is machine-agnostic (WORKSPACE_BASE/ placeholders);
    after restoring it we re-resolve each agent's workspace under the target
    machine's root (or a user-provided --workspace-root) and bake real values
    into system_prompt + agent_docs. Idempotent.

    Runs the drop_projects_segment migration first (also idempotent) so a
    legacy install with files under <base>/projects/ moves them to the new
    <base>/<slug>/ layout before the identity backfill runs. On a fresh
    install this is a no-op.
    """
    print("\n[8.5/10] identity backfill  (real id + workspace + docs)")
    # The workspace root override must reach BOTH scripts. Without it the
    # migration below falls back to the `workspace.base_dir` SETTINGS document
    # and moves real directories under it — which is how a seed against a test
    # or scratch database could touch a live install's agent folders. The
    # backfill already honoured WORKSPACE_ROOT; this one silently did not.
    ws_override = os.environ.get("WORKSPACE_ROOT", "").strip()

    # First, drop the legacy 'projects/' segment if it exists (no-op on a
    # fresh install; safe to run on every seed).
    drop_cmd = [sys.executable, "scripts/seeds/in/drop_projects_segment.py"]
    if ws_override:
        drop_cmd += ["--base-dir", ws_override]
    subprocess.run(drop_cmd, cwd=str(BACKEND_DIR))

    # Then the identity backfill, limited to the agents step 8 inserted (an
    # empty set is meaningful: nothing was added, so nothing gets rewritten).
    cmd = [sys.executable, "scripts/seeds/in/backfill_agent_identity.py"]
    if ws_override:
        cmd += ["--workspace-root", ws_override]
    cmd += ["--only-ids", ",".join(str(i) for i in sorted(_SEEDED_AGENT_IDS))]
    subprocess.run(cmd, cwd=str(BACKEND_DIR), check=True)


def step_skills() -> None:
    """Sync SKILL.md files from backend/skills/ into the skills table (FS -> DB).

    Scans BOTH roots: the builtin folder and the personal root (both under
    backend/skills/, counts printed below). The app's startup sync only scans the
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

    # THREE roots. The docstring has always claimed the personal skills live at
    # backend/skills/<id>/, but PERSONAL_SKILLS_ROOT points at
    # backend/skills/personal — so the top-level dirs were never scanned and six
    # skills that exist in the live database (and on disk) were missing from
    # every fresh install: erp-analyst, market-wizard, report-generator,
    # sql-analyst, sunhing-analyst, web-content-analyzer.
    #
    # Order is builtin -> personal -> top level, and the FIRST parse of a given
    # skill_id wins. 14 of the 21 top-level dirs duplicate a personal skill, so
    # this adds the missing ones without re-syncing (and rewriting) the rest.
    skills_root = Path(PERSONAL_SKILLS_ROOT).parent
    candidates: list = list(scan_builtin_skills())
    for md in PERSONAL_SKILLS_ROOT.rglob("SKILL.md"):
        if "builtin" not in md.parts:
            candidates.append(md)
    candidates += sorted(skills_root.glob("*/SKILL.md"))

    # A stray directory must never break an install: backend/skills/market_wizard
    # duplicates market-wizard under an id the model rejects (Skill validates
    # kebab-case), which raised ValueError and aborted the whole seed the moment
    # the top-level root entered the scan.
    parsed: dict = {}
    skipped: list = []
    for skill_md in candidates:
        try:
            data = fs_to_db_dict(skill_md)
        except Exception as exc:                      # noqa: BLE001 - reported below
            skipped.append((skill_md, exc))
            continue
        data["source_type"] = derive_source_type(skill_md)
        parsed.setdefault(data["skill_id"], data)

    synced = 0
    with SessionLocal() as db:
        for data in parsed.values():
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
                # The model validates skill_id (kebab-case) on construction, so an
                # invalid directory fails HERE, not in fs_to_db_dict above.
                # Construct first and skip without touching the session: a
                # rollback would discard every skill added earlier in this loop.
                try:
                    obj = SkillModel(**data)
                except Exception as exc:              # noqa: BLE001 - reported below
                    skipped.append((data.get("skill_id"), exc))
                    continue
                db.add(obj)
                synced += 1
        db.commit()

    for where, exc in skipped:
        label = (where.relative_to(skills_root.parent)
                 if isinstance(where, Path) else where)
        print(f"  !! skipped {label}: {exc}")
    print(f"  -> {synced} skill(s) synced, {len(skipped)} skipped "
          f"(total in DB: {_table_count('skills')})")


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
        help="TRUNCATE deep_agent_templates and custom_tools, then restore the "
             "baseline from the merge files. Destructive: agent chat "
             "sessions go too.",
    )
    args = parser.parse_args()

    print("LangConfig DB seed-all bootstrap")
    step_init_server()
    step_init_db()
    step_schema_version()
    step_settings()
    step_models()
    step_search_providers()
    step_team_settings()
    step_custom_tools(replace=args.replace)
    step_deep_agents(replace=args.replace)
    step_identity()
    step_skills()
    step_chinook()
    summary()
    # No duplicate report here. The union matches on tool_id, so a teammate's
    # `my_current_time` and the catalog's `current_time` both survive — which is
    # the correct outcome for a migration: it cannot know two differently-named
    # ids are "the same tool", and guessing by name would drop real ones. The
    # Tool Library is the place to resolve that: the user sees both rows and
    # deletes the one they do not want. check_tool_overlap.py remains for an
    # on-demand bulk look.

    print("\nDone. Start the backend (uv run python main.py), then the frontend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
