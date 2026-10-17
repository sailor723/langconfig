"""Prove the seed leaves a teammate's OWN rows byte-identical.

Drops pre-existing state that the previous verification could not distinguish:

  1. their agent's config.system_prompt and agent_docs are hashed before and
     after a full seed_all run — the identity backfill used to rewrite EVERY
     agent, baking this machine's workspace into rows that were not ours;
  2. a catalogue model they enriched (pricing/vision metadata) keeps it —
     seed_models.py used to overwrite capabilities from the per-provider default;
  3. their agent and tool rows survive, and a second run changes nothing.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, IN_DIR, OUT_DIR, REPO, SEEDS  # noqa: E402


from sqlalchemy import create_engine, text          # noqa: E402
from sqlalchemy.engine import make_url              # noqa: E402
from db.database import SessionLocal, engine        # noqa: E402

URL = engine.url.render_as_string(hide_password=False)
assert "langconfig_seedtest" in URL, f"refusing to run outside the scratch DB: {URL}"


def psql(sql: str) -> str:
    p = subprocess.run(["psql", URL, "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"psql failed: {p.stderr.strip()}")
    return p.stdout.strip()


def run_seed() -> None:
    env = {**os.environ,
           "POSTGRES_DB": "langconfig_seedtest",
           "WORKSPACE_ROOT": "/tmp/langconfig_seedtest_ws"}
    p = subprocess.run([sys.executable, "scripts/seeds/in/seed_all.py"],
                       cwd=str(BACKEND), env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"seed_all failed:\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
    tail = [l for l in p.stdout.splitlines()
            if "identity backfill" in l or "agent(s) added" in l or "limited to" in l]
    print("   " + "\n   ".join(tail))


def fingerprint() -> dict:
    """Hash of everything a teammate owns that the seed must not touch."""
    with engine.connect() as c:
        agent = c.execute(text("""
            SELECT config->>'system_prompt', agent_docs::text, name, description
            FROM deep_agent_templates WHERE name = 'teammate own agent'
        """)).fetchone()
        tool = c.execute(text(
            "SELECT name, description, implementation_config::text FROM custom_tools "
            "WHERE tool_id = 'teammate_tool'")).fetchone()
        model = c.execute(text(
            "SELECT capabilities::text FROM models WHERE model_id = 'deepseek-chat'")).fetchone()
        session = c.execute(text(
            "SELECT session_id, agent_id FROM chat_sessions")).fetchone()
    h = lambda v: hashlib.sha256(str(v).encode()).hexdigest()[:16]
    return {
        "agent_prompt": h(agent[0]),
        "agent_docs": h(agent[1]),
        "agent_meta": h((agent[2], agent[3])),
        "tool": h((tool[0], tool[1], tool[2])),
        "model_caps": h(model[0]),
        "session": str(session),
        "agent_count": int(psql("SELECT count(*) FROM deep_agent_templates")),
        "tool_count": int(psql("SELECT count(*) FROM custom_tools")),
    }


# This script owns the scratch DB it asserts on, exactly like verify_additive_seed
# does — otherwise it silently depended on that script having been run first, and
# failed with "'NoneType' object is not subscriptable" when it had not.
print("1. resetting the scratch DB and simulating a teammate")
psql("TRUNCATE deep_agent_templates, custom_tools, chat_sessions RESTART IDENTITY CASCADE")
db = SessionLocal()
try:
    db.execute(text("""
        INSERT INTO deep_agent_templates
            (name, description, category, config, middleware_config, subagents_config,
             backend_config, guardrails_config, usage_count, version, is_public, is_community, lock_version)
        VALUES ('teammate own agent', 'mine, not the team''s', 'Custom',
                '{"model":"deepseek-chat","system_prompt":"MY PROMPT, HANDS OFF"}'::json,
                '[]'::json, '[]'::json, '{}'::json, '{}'::json, 0, '1.0.0', true, false, 1)
    """))
    db.execute(text("""
        INSERT INTO custom_tools (tool_id, name, description, tool_type, implementation_config,
                                  input_schema, is_template_based, is_advanced_mode, is_public,
                                  usage_count, error_count, version, is_builtin, tags, created_at, updated_at)
        VALUES ('teammate_tool', 'Teammate Tool', 'mine', 'python_function', '{}'::json,
                '{}'::json, false, false, true, 0, 0, '1.0.0', false, '[]'::json, now(), now())
    """))
    their_id = db.execute(text(
        "SELECT id FROM deep_agent_templates WHERE name = 'teammate own agent'")).scalar()
    db.execute(text("""
        INSERT INTO chat_sessions (agent_id, session_id, messages, metrics, is_active,
                                   total_cost_usd, rag_context_tokens)
        VALUES (:aid, 'teammate-session-1', '[{"role":"user","content":"hi"}]'::json,
                '{}'::json, true, 0.0, 0)
    """), {"aid": their_id})
    db.commit()
finally:
    db.close()

print("1b. a catalogue row the teammate enriched (per-model pricing + vision)")
psql("""INSERT INTO models (model_id, display_name, provider, source, is_active, capabilities, tags,
                            is_validated, usage_count, created_at, updated_at)
        VALUES ('deepseek-chat', 'DeepSeek Chat (my edits)', 'deepseek', 'cloud', true,
                '{"streaming": true, "tools": true, "vision": true, "max_context": 64000,
                  "input_price": 0.42, "my_own_note": "teammate wrote this"}'::json, '[]'::json,
                false, 0, now(), now())
        ON CONFLICT (model_id) DO UPDATE SET capabilities = EXCLUDED.capabilities""")

print("2. fingerprint BEFORE")
before = fingerprint()
for k, v in before.items():
    print(f"   {k:14} {v}")

print("3. full seed_all run")
run_seed()

print("4. fingerprint AFTER")
after = fingerprint()
for k, v in after.items():
    print(f"   {k:14} {v}")

print("5. second run (idempotency)")
run_seed()
third = fingerprint()

print("\n=== verdict ===")
checks = [
    ("their agent's system_prompt byte-identical", after["agent_prompt"] == before["agent_prompt"]),
    ("their agent's docs byte-identical", after["agent_docs"] == before["agent_docs"]),
    ("their agent's name/description unchanged", after["agent_meta"] == before["agent_meta"]),
    ("their tool unchanged", after["tool"] == before["tool"]),
    ("their enriched model capabilities preserved", after["model_caps"] == before["model_caps"]),
    ("their chat session unchanged", after["session"] == before["session"]),
    ("baseline agents were added", after["agent_count"] > before["agent_count"]),
    ("tools were added, not replaced", after["tool_count"] >= before["tool_count"]),
    ("second run changed nothing", third == after),
]
for label, ok in checks:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")
print("\n" + ("ALL CHECKS PASSED" if all(o for _, o in checks) else "SOME CHECKS FAILED"))
