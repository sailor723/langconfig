"""Prove the agent seed is ADDITIVE: a teammate's own agents must survive it.

Runs against a scratch database (POSTGRES_DB=langconfig_seedtest) with:
  1. schema created,
  2. a simulated teammate: their own agent, their own tool, a chat session on it,
     plus an agent deliberately named the same as one in the shared baseline,
  3. the new deep_agents_merge.sql applied exactly as seed_all does,
  4. assertions.

No filesystem work, so a live install is never touched.
"""
import os
import subprocess
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, AGENTS_MERGE  # noqa: E402


from sqlalchemy import text                      # noqa: E402
from db.database import SessionLocal, engine     # noqa: E402

SEED = AGENTS_MERGE
URL = engine.url.render_as_string(hide_password=False)
assert "langconfig_seedtest" in URL, f"refusing to run outside the scratch DB: {URL}"


def psql(sql: str) -> str:
    p = subprocess.run(
        ["psql", URL, "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise SystemExit(f"psql failed: {p.stderr.strip()}")
    return p.stdout.strip()


def apply_seed() -> None:
    p = subprocess.run(
        ["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(SEED)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise SystemExit(f"seed failed: {p.stderr.strip()}\n{p.stdout[-500:]}")


print("1. creating schema …")
subprocess.run([sys.executable, "-c",
                "from db.database import init_db; init_db()"], cwd=BACKEND, check=True)
# each verification owns the scratch DB it asserted on, so it can be run either
# order and more than once — a previous run's rows must not be counted as ours
psql("TRUNCATE deep_agent_templates, custom_tools, chat_sessions RESTART IDENTITY CASCADE")

print("2. simulating a teammate …")
db = SessionLocal()
try:
    db.execute(text("""
        INSERT INTO deep_agent_templates
            (name, description, category, config, middleware_config, subagents_config,
             backend_config, guardrails_config, usage_count, version, is_public, is_community, lock_version)
        VALUES ('teammate own agent', 'mine, not the team''s', 'Custom', '{"model":"deepseek-chat"}'::json,
                '[]'::json, '[]'::json, '{}'::json, '{}'::json, 0, '1.0.0', true, false, 1)
    """))
    # same NAME as a baseline agent — the seed must leave the teammate's version alone
    db.execute(text("""
        INSERT INTO deep_agent_templates
            (name, description, category, config, middleware_config, subagents_config,
             backend_config, guardrails_config, usage_count, version, is_public, is_community, lock_version)
        VALUES ('db query', 'TEAMMATE VERSION', 'Custom', '{"model":"deepseek-chat"}'::json,
                '[]'::json, '[]'::json, '{}'::json, '{}'::json, 0, '1.0.0', true, false, 1)
    """))
    db.execute(text("""
        INSERT INTO custom_tools (tool_id, name, description, tool_type, implementation_config,
                                  input_schema, is_template_based, is_advanced_mode, is_public,
                                  usage_count, error_count, version, is_builtin, tags, created_at, updated_at)
        VALUES ('teammate_tool', 'Teammate Tool', 'mine', 'python_function', '{}'::json,
                '{}'::json, false, false, true,
                0, 0, '1.0.0', false, '[]'::json, now(), now())
    """))
    their_agent_id = db.execute(text(
        "SELECT id FROM deep_agent_templates WHERE name = 'teammate own agent'")).scalar()
    db.execute(text("""
        INSERT INTO chat_sessions (agent_id, session_id, messages, metrics, is_active,
                                   total_cost_usd, rag_context_tokens)
        VALUES (:aid, 'teammate-session-1', '[{"role":"user","content":"hi"}]'::json, '{}'::json, true,
                0.0, 0)
    """), {"aid": their_agent_id})
    db.commit()
finally:
    db.close()

before = {
    "agents": int(psql("SELECT count(*) FROM deep_agent_templates")),
    "teammate_agent_id": int(psql("SELECT id FROM deep_agent_templates WHERE name='teammate own agent'")),
    "sessions": int(psql("SELECT count(*) FROM chat_sessions")),
    "tools": int(psql("SELECT count(*) FROM custom_tools")),
}
print(f"   before: {before}")

print("3. applying deep_agents_merge.sql …")
apply_seed()

after = {
    "agents": int(psql("SELECT count(*) FROM deep_agent_templates")),
    "teammate_agent_id": int(psql("SELECT id FROM deep_agent_templates WHERE name='teammate own agent'")),
    "sessions": int(psql("SELECT count(*) FROM chat_sessions")),
    "tools": int(psql("SELECT count(*) FROM custom_tools")),
    "team_version_of_dbquery": psql("SELECT description FROM deep_agent_templates WHERE name='db query'"),
    "their_session_agent": psql("SELECT agent_id FROM chat_sessions WHERE session_id='teammate-session-1'"),
}
print(f"   after:  {after}")

print("4. re-applying (idempotency) …")
apply_seed()
again = int(psql("SELECT count(*) FROM deep_agent_templates"))
print(f"   agents after a second run: {again}")

print("\n=== verdict ===")
checks = [
    ("teammate's agent kept its id", after["teammate_agent_id"] == before["teammate_agent_id"]),
    ("teammate's agent not renamed/removed",
     psql("SELECT description FROM deep_agent_templates WHERE name='teammate own agent'") == "mine, not the team's"),
    ("teammate's chat session survived", after["sessions"] == before["sessions"] == 1),
    ("session still points at their agent",
     after["their_session_agent"] == str(before["teammate_agent_id"])),
    ("their tool untouched", after["tools"] == before["tools"] == 1),
    ("baseline agents were added", after["agents"] > before["agents"]),
    ("name clash kept THEIR version", after["team_version_of_dbquery"] == "TEAMMATE VERSION"),
    ("second run inserted nothing", again == after["agents"]),
]
for label, ok in checks:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")
print("\n" + ("ALL CHECKS PASSED" if all(o for _, o in checks) else "SOME CHECKS FAILED"))
