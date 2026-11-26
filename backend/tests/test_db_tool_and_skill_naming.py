"""The naming split between DB TOOLS and DB SKILLS, and the drift gate that keeps them honest.

Two namespaces describe the same capability from two sides:

* a **tool** (`custom_tools.tool_id`) is a capability — snake_case, `db_*` for the database family;
* a **skill** (`skills.skill_id`) is a procedure — kebab-case, `db-*` for the database family.

They are stored in different tables and loaded by different code, so nothing stops a rename in one from
leaving a stale name in the other. That drift is exactly what happened here: `pg_query` → `db_query_agent`
left `pg_query` in `to-validation`'s `allowed_tools`, and a deprecated `db_dashboard` stayed in
`db-excel-to-postgres` and in agent 375's tool list. Neither broke anything — that is the problem.

What is pinned:

* every live tool id is snake_case; every `db_*` tool sits in the `database` category;
* every `db-` skill id is kebab-case (and the eight database skills carry that prefix);
* **drift**: every name in an agent's `native_tools` and in a skill's `allowed_tools` is either a live
  tool or a documented SDK/native name — a retired or renamed tool must not survive in a config.
"""
from __future__ import annotations

import re

from db.database import SessionLocal
from models.custom_tool import CustomTool
from models.deep_agent import DeepAgentTemplate
from models.skill import Skill

#: Names an agent may hold that are NOT `custom_tools` rows: the SDK's own filesystem / planning /
#: memory / delegation tools plus the platform's shell and web entry points. Kept explicit on purpose —
#: a new name here is a decision, not a default.
SDK_NATIVE_TOOLS = {
    "bash", "execute", "shell", "python", "python_execute", "browser",
    "read_file", "write_file", "edit_file", "glob", "grep", "ls", "list_files", "read_any_file",
    "read_image", "delete_file", "rename_file", "move_file", "mkdir", "save_document",
    "write_todos", "read_todos", "think_tool", "reasoning_chain", "task", "skill",
    "memory_store", "memory_recall", "web_search", "web_fetch", "fetch_url", "tavily_search",
    "serpapi_search", "filesystem", "register_database",
}

DB_SKILLS = {
    "db-excel-to-postgres", "db-sql-query", "db-sql-analyst", "db-sqlite-to-postgres",
    "db-ontology-build", "db-ontology-dashboard", "db-ontology-metrics", "db-ontology-ask",
}


def _load():
    """Sync session on purpose: these are pure catalogue reads, and an async engine is bound to the
    event loop that created it — `asyncio.run` per test then raises "attached to a different loop"."""
    db = SessionLocal()
    try:
        return db.query(CustomTool).all(), db.query(DeepAgentTemplate).all(), db.query(Skill).all()
    finally:
        db.close()


def test_tool_ids_are_snake_case_and_db_tools_live_in_the_database_category():
    tools, _, _ = _load()
    bad = [t.tool_id for t in tools if not re.fullmatch(r"[a-z0-9_]+", t.tool_id or "")]
    assert not bad, f"tool ids that are not snake_case: {bad}"
    mis_categorised = [(t.tool_id, t.category) for t in tools
                       if (t.tool_id or "").startswith("db_") and (t.category or "") != "database"]
    assert not mis_categorised, f"`db_*` tools outside the database category: {mis_categorised}"


def test_database_skill_ids_are_kebab_case_and_carry_the_prefix():
    _, _, skills = _load()
    ids = {s.skill_id for s in skills}
    bad = [i for i in ids if not re.fullmatch(r"[a-z0-9-]+", i or "")]
    assert not bad, f"skill ids that are not kebab-case: {bad}"
    present = DB_SKILLS & ids
    assert present, "the eight database skills should exist after the rename"
    for old in ("excel-csv-to-postgres", "sql-query", "sql-analyst", "sqlite-to-postgres",
                "build-ontology-from-db", "build-ontology-dashboard", "edit-ontology-metrics",
                "answer-ontology-question"):
        assert old not in ids, f"old skill id {old!r} survived the rename"


def test_no_agent_binds_a_tool_that_is_not_live():
    tools, agents, _ = _load()
    live = {t.tool_id for t in tools if not t.is_deprecated}
    drift = {}
    for a in agents:
        names = set((a.config or {}).get("native_tools") or [])
        unknown = sorted(names - live - SDK_NATIVE_TOOLS)
        if unknown:
            drift[a.id] = unknown
    assert not drift, f"agents binding tools that are retired or gone: {drift}"


def test_no_subagent_expert_binds_a_tool_that_is_not_live():
    """Subagent specs are the third place a tool name lives — and the one that drifted unnoticed.

    Measured 2026-11-25: the ontology builder's `tables` / `modeller` / `metrics` experts still named
    `db_query`, a tool deleted hours earlier, while `board` was missing the `ontology_inspect` its own
    design doc requires. Nothing failed: the experts simply could not do their job, and no gate looked
    at `config.subagents[].tools`.
    """
    tools, agents, _ = _load()
    live = {t.tool_id for t in tools if not t.is_deprecated}
    drift = {}
    for a in agents:
        for sa in (a.config or {}).get("subagents") or []:
            if not isinstance(sa, dict):
                continue
            unknown = sorted(set(sa.get("tools") or []) - live - SDK_NATIVE_TOOLS)
            if unknown:
                drift[f"{a.id}:{sa.get('name')}"] = unknown
    assert not drift, f"subagent experts naming tools that are retired or gone: {drift}"


def test_no_builtin_skill_allows_a_tool_that_is_not_live():
    """Built-in skills are OURS: a retired tool must not survive in them.

    Personal skills (`source_type=personal`) are the user's own content — rewriting them from a test
    would be editing user data, so they are reported below instead of asserted. Their drift is real
    (a skill that says "use sqlite_execute" now points at nothing), which is why the report exists.
    """
    tools, _, skills = _load()
    live = {t.tool_id for t in tools if not t.is_deprecated}
    drift, personal_drift = {}, {}
    for s in skills:
        allowed = s.allowed_tools or []
        if not isinstance(allowed, list):
            continue
        unknown = sorted({a for a in allowed if isinstance(a, str)} - live - SDK_NATIVE_TOOLS)
        if not unknown:
            continue
        # `source_type` is an enum whose str() is like "SkillSourceType.PERSONAL" — match loosely
        if "personal" in str(getattr(s, "source_type", "")).lower():
            personal_drift[s.skill_id] = unknown
        else:
            drift[s.skill_id] = unknown
    if personal_drift:
        print(f"\n  personal skills naming retired tools (yours to fix): {personal_drift}\n")
    assert not drift, f"builtin skills naming tools that are retired or gone: {drift}"
