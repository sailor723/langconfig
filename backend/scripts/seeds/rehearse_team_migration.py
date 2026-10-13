"""Rehearse the whole team-migration loop in isolation, in the real order.

    the owner installs  ->  the teammate installs and starts working
    ->  the owner SEEDS OUT + COMMITS  ->  the teammate PULLS THE REPO  ->  SEEDS

The other verify_* scripts test the merge SQL in place. This one rehearses the
actual delivery: two machines, two databases, and a teammate who already has
their own agents, tools, a chat session, and a setting they changed themselves
before the team's new work ever reaches them.

Two guarantees are checked, and the second is the one that quietly breaks:

 1. nothing of theirs is lost or rewritten — every one of their rows is compared
    by an md5 of the entire row, before and after;
 2. what a teammate installs is *identical* to what the owner has — the baseline
    tool set from their fresh install must equal the owner's, exactly. A stale row
    hiding in an artefact that only applies to empty tables (custom_tools_dump.sql)
    is enough to break this, and it did.

Nothing outside the sandbox is written: every step runs in throwaway clones under
/tmp, every database is a scratch one, and both the real working tree and the real
database are asserted untouched at the end. WORKSPACE_ROOT is forced into /tmp
because step_identity otherwise falls back to the ``workspace.base_dir`` settings
document and can MOVE a live install's agent folders.

    .venv/bin/python scripts/seeds/rehearse_team_migration.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]        # backend/scripts/seeds/ -> repo root
BACKEND = REPO / "backend"
SCRATCH = Path("/tmp/langconfig-rehearsal")
OWNER = SCRATCH / "owner"                         # the baseline owner's machine
TEAM = SCRATCH / "teammate"                       # the teammate's machine
WS_OWNER = "/tmp/langconfig-rehearsal-ws/owner"
WS_TEAM = "/tmp/langconfig-rehearsal-ws/teammate"

OWNER_DB = "langconfig_teamorigin"
TEAM_DB = "langconfig_mockteam"

# the teammate's own work, plus a clash against the team baseline in each table
THEIRS_AGENTS = ["Teammate Pricing Agent", "HR Headcount Agent"]
THEIRS_TOOLS = ["tm_price_scraper", "tm_kpi_board"]
CLASH_AGENT = "Deep Architect"        # a baseline agent, matched by name
CLASH_TOOL = "current_time"           # a baseline tool, matched by canonical tool_id
LATER_AGENT = "Teammate QA Agent"     # created after their install, before delivery 2
LATER_TOOL = "tm_qa_report"
THEIR_DESC = "TEAMMATE VERSION — ours, do not overwrite"
LOCAL_SETTING = 9999                  # vs a code default and team seed of 120

# what the OWNER invents after the teammate has installed
NEW_AGENT = "Team KPI Agent"
NEW_TOOL = "team_kpi_query"

sys.path.insert(0, str(BACKEND))
from dotenv import load_dotenv                                        # noqa: E402
from sqlalchemy import create_engine, text                            # noqa: E402
from sqlalchemy.engine import make_url                                # noqa: E402

load_dotenv(REPO / ".env")
from db.db_url import compose_db_url                                  # noqa: E402

REAL_URL = make_url(compose_db_url())
REAL_DB = REAL_URL.database
assert REAL_DB not in (OWNER_DB, TEAM_DB), "mock DBs must not be the real database"
MAINT = REAL_URL.set(database="postgres").render_as_string(hide_password=False)
OWNER_URL = REAL_URL.set(database=OWNER_DB).render_as_string(hide_password=False)
TEAM_URL = REAL_URL.set(database=TEAM_DB).render_as_string(hide_password=False)


def banner(step, title):
    print(f"\n{'═' * 78}\n  {step}  {title}\n{'═' * 78}")


def sh(args, cwd=None, env=None, check=True, quiet=True):
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if check and p.returncode != 0:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:])
        raise SystemExit(f"command failed ({p.returncode}): {' '.join(map(str, args))}")
    if not quiet:
        for ln in (p.stdout or "").splitlines():
            print(f"    {ln}")
    return p


def psql(url, sql):
    return sh(["psql", url, "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql]).stdout.strip()


def q(url, sql):
    with create_engine(url).connect() as c:
        return c.execute(text(sql)).scalar()


def rows(url, sql):
    with create_engine(url).connect() as c:
        return {r[0] for r in c.execute(text(sql))}


def run_script(clone, script, db, ws, extra=()):
    """Run a repo script the way the runbook does: from backend/, via .venv."""
    env = dict(os.environ, POSTGRES_DB=db, WORKSPACE_ROOT=ws)
    return sh([str(clone / "backend/.venv/bin/python"), script, *extra],
              cwd=clone / "backend", env=env, check=False)


def seed(clone, db, ws, label):
    p = run_script(clone, "scripts/seeds/seed_all.py", db, ws)
    print(f"  {label}: seed_all.py -> exit {p.returncode}")
    if p.returncode != 0:
        print(p.stdout[-2500:])
        print(p.stderr[-2000:])
        raise SystemExit(f"{label}: seed failed")
    return p


def prepare_clone(clone, db, ws):
    """Give a clone the two things the runbook says a teammate must supply."""
    out = []
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("POSTGRES_DB="):
            out.append(f"POSTGRES_DB={db}")
        elif line.startswith("LANGCONFIG_WORKSPACE_ROOT="):
            out.append(f"LANGCONFIG_WORKSPACE_ROOT={Path(ws).parent}")
        else:
            out.append(line)
    (clone / ".env").write_text("\n".join(out) + "\n")
    venv = clone / "backend/.venv"
    if not venv.exists():
        venv.symlink_to(BACKEND / ".venv")
    sh([str(venv / "bin/python"), "-c", "import sqlalchemy, fastapi"])


def init_schema(clone, db, ws):
    sh([str(clone / "backend/.venv/bin/python"), "-c",
        "from db.database import init_db; init_db()"],
       cwd=clone / "backend", env=dict(os.environ, POSTGRES_DB=db, WORKSPACE_ROOT=ws))


def row_hash(url, table, key_col, key_val):
    return q(url, f"SELECT md5(t::text) FROM {table} t WHERE {key_col} = '{key_val}'")


def add_agent(url, name, description=THEIR_DESC):
    with create_engine(url).begin() as c:
        return c.execute(text("""
            INSERT INTO deep_agent_templates
                (name, description, category, config, middleware_config, subagents_config,
                 backend_config, guardrails_config, usage_count, version, is_public, is_community, lock_version)
            VALUES (:n, :d, 'Custom', '{"model":"deepseek-chat"}'::json,
                    '[]'::json, '[]'::json, '{}'::json, '{}'::json, 0, '1.0.0', true, false, 1)
            RETURNING id
        """), {"n": name, "d": description}).scalar()


def add_tool(url, tool_id, description=THEIR_DESC):
    with create_engine(url).begin() as c:
        c.execute(text("""
            INSERT INTO custom_tools (tool_id, name, description, tool_type, implementation_config,
                                      input_schema, is_template_based, is_advanced_mode, is_public,
                                      usage_count, error_count, version, is_builtin, tags, created_at, updated_at)
            VALUES (:t, :t, :d, 'python_function', '{}'::json, '{}'::json, false, false, true,
                    0, 0, '1.0.0', false, '[]'::json, now(), now())
        """), {"t": tool_id, "d": description})


# ── stage 0: sandbox ─────────────────────────────────────────────────────────
banner("STAGE 0", "sandbox — two throwaway clones + two scratch databases")
if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
SCRATCH.mkdir(parents=True)
for ws in (WS_OWNER, WS_TEAM):
    shutil.rmtree(Path(ws), ignore_errors=True)
    Path(ws).mkdir(parents=True, exist_ok=True)

head = sh(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"]).stdout.strip()
print(f"  real repo, read-only from here   HEAD {head}")
print(f"  real database, never used        {REAL_DB}")

sh(["git", "clone", "--local", "--quiet", str(REPO), str(OWNER)])
prepare_clone(OWNER, OWNER_DB, WS_OWNER)
for db in (OWNER_DB, TEAM_DB):
    psql(MAINT, f'DROP DATABASE IF EXISTS "{db}"')
    psql(MAINT, f'CREATE DATABASE "{db}"')
    print(f"  fresh scratch database           {db}")

# ── stage 1: the owner's install is the reference ────────────────────────────
banner("STAGE 1", "the owner's machine — install from the repo, and remember what it got")
seed(OWNER, OWNER_DB, WS_OWNER, "owner")
owner_tools = rows(OWNER_URL, "SELECT tool_id FROM custom_tools")
owner_agents = rows(OWNER_URL, "SELECT name FROM deep_agent_templates")
print(f"  owner's install: {len(owner_agents)} agents, {len(owner_tools)} tools")
print(f"  a fresh install contains a 'write_file' tool row: {'write_file' in owner_tools}")

# ── stage 2: the teammate arrives ────────────────────────────────────────────
banner("STAGE 2", "the teammate — clone the SAME commit, install, and bring their own work")
sh(["git", "clone", "--local", "--quiet", str(OWNER), str(TEAM)])
prepare_clone(TEAM, TEAM_DB, WS_TEAM)
print(f"  teammate clone HEAD {sh(['git', '-C', str(TEAM), 'rev-parse', '--short', 'HEAD']).stdout.strip()}"
      f" (same as owner: {head})")
init_schema(TEAM, TEAM_DB, WS_TEAM)

for a in THEIRS_AGENTS + [CLASH_AGENT]:
    add_agent(TEAM_URL, a)
for t in THEIRS_TOOLS + [CLASH_TOOL]:
    add_tool(TEAM_URL, t)
their_agent_id = add_agent(TEAM_URL, "Teammate Reporting Agent")
with create_engine(TEAM_URL).begin() as c:
    c.execute(text("""
        INSERT INTO chat_sessions (agent_id, session_id, messages, metrics, is_active,
                                   total_cost_usd, rag_context_tokens)
        VALUES (:aid, 'teammate-session-1', '[{"role":"user","content":"hi"}]'::json,
                '{}'::json, true, 0.0, 0)
    """), {"aid": their_agent_id})

their_agents = THEIRS_AGENTS + [CLASH_AGENT, "Teammate Reporting Agent"]
their_tools = THEIRS_TOOLS + [CLASH_TOOL]
before1 = {
    "agents": q(TEAM_URL, "SELECT count(*) FROM deep_agent_templates"),
    "tools": q(TEAM_URL, "SELECT count(*) FROM custom_tools"),
    "sessions": q(TEAM_URL, "SELECT count(*) FROM chat_sessions"),
    "agent_hashes": {a: row_hash(TEAM_URL, "deep_agent_templates", "name", a) for a in their_agents},
    "tool_hashes": {t: row_hash(TEAM_URL, "custom_tools", "tool_id", t) for t in their_tools},
}
print(f"  teammate's own DB before any seed: {before1['agents']} agents, "
      f"{before1['tools']} tools, {before1['sessions']} chat session")
print(f"    agents: {', '.join(their_agents)}")
print(f"    tools:  {', '.join(their_tools)}")

# ── stage 3: first delivery ──────────────────────────────────────────────────
banner("STAGE 3", "THEN SEED (delivery 1) — the team baseline arrives on top of their work")
seed(TEAM, TEAM_DB, WS_TEAM, "teammate")
after1 = {
    "agents": q(TEAM_URL, "SELECT count(*) FROM deep_agent_templates"),
    "tools": q(TEAM_URL, "SELECT count(*) FROM custom_tools"),
    "sessions": q(TEAM_URL, "SELECT count(*) FROM chat_sessions"),
    "tool_set": rows(TEAM_URL, "SELECT tool_id FROM custom_tools"),
    "agent_set": rows(TEAM_URL, "SELECT name FROM deep_agent_templates"),
    "clash_agent": q(TEAM_URL, f"SELECT description FROM deep_agent_templates WHERE name = '{CLASH_AGENT}'"),
    "clash_agent_rows": q(TEAM_URL, f"SELECT count(*) FROM deep_agent_templates WHERE name = '{CLASH_AGENT}'"),
    "clash_tool": q(TEAM_URL, f"SELECT description FROM custom_tools WHERE tool_id = '{CLASH_TOOL}'"),
    "session_agent": q(TEAM_URL, "SELECT agent_id FROM chat_sessions WHERE session_id = 'teammate-session-1'"),
}
print(f"  after: {after1['agents']} agents, {after1['tools']} tools, {after1['sessions']} chat session")
# their set after the seed is the union of the owner's set and their own: nothing
# missing (compare the whole sets, not a subtraction — an id they happen to share
# with the baseline, like the current_time clash, would vanish from a subtraction)
expected_tools = owner_tools | set(their_tools)
expected_agents = owner_agents | set(their_agents)
same_tools = after1["tool_set"] == expected_tools
same_agents = after1["agent_set"] == expected_agents
print(f"  baseline tools they now hold: {len(after1['tool_set'])} "
      f"(owner's {len(owner_tools)} + their {len(set(their_tools) - owner_tools)} new)")
print(f"  that set equals the owner's union their own: tools={same_tools} agents={same_agents}")

# ── stage 4: the teammate keeps working ──────────────────────────────────────
banner("STAGE 4", "the teammate keeps working — more of their own work, and a setting they change")
later_agent_id = add_agent(TEAM_URL, LATER_AGENT)
add_tool(TEAM_URL, LATER_TOOL)
psql(TEAM_URL, "UPDATE settings_documents SET document = jsonb_set(document::jsonb, "
               "'{analysis_chat_timeout}', '9999')::json WHERE ns = 'runtime'")
readback = q(TEAM_URL, "SELECT document ->> 'analysis_chat_timeout' "
                       "FROM settings_documents WHERE ns = 'runtime'")
print(f"  added agent {LATER_AGENT!r} (id {later_agent_id}) and tool {LATER_TOOL!r}")
print(f"  changed runtime.analysis_chat_timeout to {readback!r} "
      f"(team seed and code default: 120)")
assert readback == str(LOCAL_SETTING), f"the local edit did not stick: {readback!r}"
before2 = {
    "agents": q(TEAM_URL, "SELECT count(*) FROM deep_agent_templates"),
    "tools": q(TEAM_URL, "SELECT count(*) FROM custom_tools"),
    "agent_hash": row_hash(TEAM_URL, "deep_agent_templates", "name", LATER_AGENT),
    "tool_hash": row_hash(TEAM_URL, "custom_tools", "tool_id", LATER_TOOL),
}

# ── stage 5: the owner SEEDS OUT ─────────────────────────────────────────────
banner("STAGE 5", "SEED OUT — new team work exists only in the owner's database")
add_agent(OWNER_URL, NEW_AGENT, "new team work after the last export")
add_tool(OWNER_URL, NEW_TOOL, "new team work after the last export")
print(f"  owner created agent {NEW_AGENT!r} and tool {NEW_TOOL!r} in the UI")
print( "  (nothing in git knows about them yet)")

due = run_script(OWNER, "scripts/seeds/export_baseline.py", OWNER_DB, WS_OWNER, ["--check"])
print(f"\n  export_baseline.py --check -> exit {due.returncode} "
      f"({'DUE, as expected' if due.returncode == 1 else 'NOT DUE — the check missed new rows'})")
for ln in [l for l in due.stdout.splitlines() if "agents" in l or "tools" in l]:
    print(f"    {ln.strip()}")

exported = run_script(OWNER, "scripts/seeds/export_baseline.py", OWNER_DB, WS_OWNER)
fresh = run_script(OWNER, "scripts/seeds/export_baseline.py", OWNER_DB, WS_OWNER, ["--check"])
print(f"  export_baseline.py (seed out) -> exit {exported.returncode}")
print(f"  export_baseline.py --check -> exit {fresh.returncode} "
      f"({'FRESH' if fresh.returncode == 0 else 'still stale'})")
in_snapshot = (NEW_AGENT in (OWNER / "backend/scripts/seeds/deep_agents_merge.sql").read_text()
               and NEW_TOOL in (OWNER / "backend/scripts/seeds/custom_tools_merge.sql").read_text())
print(f"  the new work is now inside the snapshot artefact: {in_snapshot}")

# ── stage 6: COMMIT TO GIT ───────────────────────────────────────────────────
banner("STAGE 6", "COMMIT — the snapshot is the only thing that carries the work")
sh(["git", "-C", str(OWNER), "add", "backend/scripts/seeds"])
sh(["git", "-C", str(OWNER), "-c", "user.email=rehearsal@local", "-c", "user.name=Rehearsal",
    "commit", "--quiet", "-m", "chore(seeds): rehearsal — carry new team work"])
owner_sha = sh(["git", "-C", str(OWNER), "rev-parse", "--short", "HEAD"]).stdout.strip()
print(f"  owner commit {owner_sha}")
for ln in sh(["git", "-C", str(OWNER), "show", "--stat", "--oneline", "HEAD"]).stdout.strip().splitlines()[:6]:
    print(f"    {ln.strip()}")

# ── stage 7: THE REPO reaches the teammate ───────────────────────────────────
banner("STAGE 7", "THE REPO — the teammate pulls, and the work is in their snapshot")
pull = sh(["git", "-C", str(TEAM), "pull", "--quiet", "--ff-only"], check=False)
team_head = sh(["git", "-C", str(TEAM), "rev-parse", "--short", "HEAD"]).stdout.strip()
team_has_new = NEW_AGENT in (TEAM / "backend/scripts/seeds/deep_agents_merge.sql").read_text()
print(f"  git pull -> exit {pull.returncode}; teammate HEAD {team_head} "
      f"(owner's commit: {team_head == owner_sha})")
print(f"  the new work arrived through git, not the database: {team_has_new}")

# ── stage 8: second delivery ─────────────────────────────────────────────────
banner("STAGE 8", "THEN SEED (delivery 2) — the new work lands, theirs must not move")
seed(TEAM, TEAM_DB, WS_TEAM, "teammate")
after2 = {
    "agents": q(TEAM_URL, "SELECT count(*) FROM deep_agent_templates"),
    "tools": q(TEAM_URL, "SELECT count(*) FROM custom_tools"),
    "clash_agent": q(TEAM_URL, f"SELECT description FROM deep_agent_templates WHERE name = '{CLASH_AGENT}'"),
    "clash_tool": q(TEAM_URL, f"SELECT description FROM custom_tools WHERE tool_id = '{CLASH_TOOL}'"),
    "session_agent": q(TEAM_URL, "SELECT agent_id FROM chat_sessions WHERE session_id = 'teammate-session-1'"),
    "setting": q(TEAM_URL, "SELECT document ->> 'analysis_chat_timeout' FROM settings_documents WHERE ns = 'runtime'"),
    "owner_setting": q(OWNER_URL, "SELECT document ->> 'analysis_chat_timeout' FROM settings_documents WHERE ns = 'runtime'"),
    "new_agent": q(TEAM_URL, f"SELECT count(*) FROM deep_agent_templates WHERE name = '{NEW_AGENT}'"),
    "new_tool": q(TEAM_URL, f"SELECT count(*) FROM custom_tools WHERE tool_id = '{NEW_TOOL}'"),
    "write_file": q(TEAM_URL, "SELECT count(*) FROM custom_tools WHERE tool_id = 'write_file'"),
}
print(f"  after: {after2['agents']} agents, {after2['tools']} tools")

seed(TEAM, TEAM_DB, WS_TEAM, "teammate (a third run, for idempotency)")
stable = (q(TEAM_URL, "SELECT count(*) FROM deep_agent_templates") == after2["agents"]
          and q(TEAM_URL, "SELECT count(*) FROM custom_tools") == after2["tools"])
print(f"  counts unchanged by the extra run: {stable}")

# ── verdict ──────────────────────────────────────────────────────────────────
banner("VERDICT", f"the teammate's {before1['agents']} agents + {before1['tools']} tools, across two deliveries")
checks = [
    # what a teammate installs must equal what the owner has, plus their own work
    ("delivery 1 gave them exactly the owner's agents", same_agents),
    ("delivery 1 gave them exactly the owner's tools", same_tools),
    ("no stale 'write_file' row on a fresh install", after1["tool_set"].isdisjoint({"write_file"})),
    # nothing of theirs moved, ever
    *[(f"their agent {a!r} is byte-identical after delivery 1",
       row_hash(TEAM_URL, "deep_agent_templates", "name", a) == before1["agent_hashes"][a])
      for a in their_agents],
    *[(f"their tool {t!r} is byte-identical after delivery 1",
       row_hash(TEAM_URL, "custom_tools", "tool_id", t) == before1["tool_hashes"][t])
      for t in their_tools],
    ("the name clash kept THEIR agent, exactly one row",
     after1["clash_agent"] == THEIR_DESC and after1["clash_agent_rows"] == 1),
    (f"the tool_id clash kept THEIR {CLASH_TOOL}", after1["clash_tool"] == THEIR_DESC),
    ("their chat session survived", after1["sessions"] == before1["sessions"] == 1),
    ("their session still points at their agent",
     str(after1["session_agent"]) == str(their_agent_id)),
    # the baseline really arrived
    ("delivery 1 added the team's agents", after1["agents"] > before1["agents"]),
    ("delivery 1 added the team's tools", after1["tools"] > before1["tools"]),
    # delivery 2
    ("seed out caught the new work (--check was DUE)", due.returncode == 1),
    ("seed out wrote it into the snapshot", in_snapshot),
    ("the commit is what the teammate pulled", team_head == owner_sha and team_has_new),
    (f"their later agent {LATER_AGENT!r} survived delivery 2",
     row_hash(TEAM_URL, "deep_agent_templates", "name", LATER_AGENT) == before2["agent_hash"]),
    (f"their later tool {LATER_TOOL!r} survived delivery 2",
     row_hash(TEAM_URL, "custom_tools", "tool_id", LATER_TOOL) == before2["tool_hash"]),
    ("the clash answers still theirs after delivery 2",
     after2["clash_agent"] == THEIR_DESC and after2["clash_tool"] == THEIR_DESC),
    ("their session survived delivery 2",
     str(after2["session_agent"]) == str(their_agent_id)),
    ("their own setting was not overwritten", after2["setting"] == str(LOCAL_SETTING)),
    ("the owner's untouched value stayed the team's (merge is selective, not global)",
     after2["owner_setting"] == "120"),
    (f"the new team agent {NEW_AGENT!r} arrived", after2["new_agent"] == 1),
    (f"the new team tool {NEW_TOOL!r} arrived", after2["new_tool"] == 1),
    ("delivery 2 added the new work only (no duplicate tools)",
     after2["tools"] == before2["tools"] + 1),
    ("a third run changed nothing", stable),
    ("the real database still has its 56 agents",
     q(REAL_URL.render_as_string(hide_password=False), "SELECT count(*) FROM deep_agent_templates") == 56),
]
for label, ok in checks:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

real_dirty = [l for l in sh(["git", "-C", str(REPO), "status", "--porcelain", "backend/scripts/seeds"],
                            check=False).stdout.strip().splitlines()
              if not l.endswith(".bak") and "rehearse" not in l]
checks.append(("the real working tree's snapshot is untouched", not real_dirty))
print(f"  [{'PASS' if not real_dirty else 'FAIL'}] the real working tree's snapshot is untouched"
      + (f" {real_dirty}" if real_dirty else ""))

n_fail = sum(1 for _, ok in checks if not ok)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
print("ALL CHECKS PASSED" if n_fail == 0 else "SOME CHECKS FAILED")
print(f"\nleft behind for inspection: {OWNER} and {TEAM}")
sys.exit(1 if n_fail else 0)
