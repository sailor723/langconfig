"""One-shot script: create two agents that wrap the advanced LangGraph tools.

The advanced SQL / Neo4j agents are already exposed as native tools
(advanced_sql_agent_tool, neo4j_agent_advanced_tool — ids 102 / 103 in
custom_tools). This script creates the two end-user agents that
DELEGATE to those tools, modeled on the existing "db query" agent
(id 198).

Run:  cd backend && .venv/bin/python scripts/create_advanced_agents.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate

# ---------------------------------------------------------------------------
# Reference template — agent 198 "db query" (read fresh in case it changes)
# ---------------------------------------------------------------------------
def _load_reference_config() -> dict:
    db = SessionLocal()
    try:
        row = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 198).first()
        if row is None:
            raise SystemExit("reference agent 198 not found — run seed_all first")
        return dict(row.config or {})
    finally:
        db.close()

REF_CONFIG = _load_reference_config()
REF_NATIVE_TOOLS = list(REF_CONFIG.get("native_tools", []))
REF_MODEL = REF_CONFIG.get("model", "deepseek-chat")
REF_TEMPERATURE = REF_CONFIG.get("temperature", 0.7)
REF_USE_DEEPAGENTS = bool(REF_CONFIG.get("use_deepagents", False))

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------
ADV_SQL_AGENT = {
    "name": "Advanced SQL Expert",
    "description": "SQL database expert that delegates analytical / multi-hop questions to the planner-based advanced SQL agent (schema discovery, action plan, monitor, synthesis). Read-only.",
    "category": "database",
    "delegation_tool": "advanced_sql_agent_tool",
    "system_prompt_prefix": (
        "you are an expert for querying SQL databases with the planner-based advanced agent. "
        "For any question about a SQL database, call the advanced_sql_agent_tool — it handles "
        "schema discovery, plans multi-step queries, and synthesizes the final answer. "
        "For simple questions it returns one query; for complex / multi-hop questions it "
        "decomposes the work into a plan and runs each step with monitoring. The tool is "
        "read-only — DML is rejected by design. Always base your answer on the tool's result."
    ),
}

ADV_NEO4J_AGENT = {
    "name": "Advanced Neo4j Graph Expert",
    "description": "Neo4j graph database expert that delegates analytical / multi-hop Cypher questions to the planner-based advanced Neo4j agent (label/schema discovery, plan, monitor, synthesis). Read-only; database-agnostic.",
    "category": "database",
    "delegation_tool": "neo4j_agent_advanced_tool",
    "system_prompt_prefix": (
        "you are an expert for querying Neo4j graph databases with the planner-based advanced agent. "
        "For any question about the graph, call the neo4j_agent_advanced_tool — it discovers "
        "the schema at runtime, plans multi-hop Cypher queries, monitors progress, and "
        "synthesizes the final answer. The tool works against any connected graph (labels, "
        "relationship types and properties are discovered from the live schema, so no "
        "hardcoding). The tool is read-only — DML is rejected by design. Always base your "
        "answer on the tool's result."
    ),
}

AGENT_DEFS = [ADV_SQL_AGENT, ADV_NEO4J_AGENT]


def _build_config(agent_def: dict) -> dict:
    """Clone agent 198's config, swap the delegation tool, set the system prompt."""
    cfg = dict(REF_CONFIG)  # shallow copy of all top-level keys
    native_tools = [t for t in REF_NATIVE_TOOLS if t != agent_def["delegation_tool"]]
    # Add our delegation tool (idempotent — list comp above may have already kept it
    # for the SQL agent, but for the Neo4j agent the original list has no neo4j
    # delegation, so we always add to be safe).
    if agent_def["delegation_tool"] not in native_tools:
        native_tools.append(agent_def["delegation_tool"])
    cfg["native_tools"] = native_tools
    cfg["model"] = REF_MODEL
    cfg["temperature"] = REF_TEMPERATURE
    cfg["use_deepagents"] = REF_USE_DEEPAGENTS
    cfg["system_prompt"] = agent_def["system_prompt_prefix"]
    return cfg


def _resolve_workspace(agent_id: int) -> str:
    """Per-agent workspace path, matching the langconfig workspace convention."""
    base = Path(__file__).resolve().parents[1]  # backend/
    return str(base / "outputs" / "agents" / f"agent_{agent_id}")


def _build_resolved_system_prompt(agent_def: dict, agent_id: int, workspace: str) -> str:
    """Full system prompt with identity block, matching the backfill template."""
    return (
        f"{agent_def['system_prompt_prefix']}\n\n"
        f"## Identity\n\n"
        f"- **Agent ID**: {agent_id}\n"
        f"- **Workspace**: {workspace}\n"
        f"- **Delegation tool**: `{agent_def['delegation_tool']}`\n\n"
        f"Always invoke the delegation tool for the user's question and return the "
        f"final answer; do not paraphrase or shorten the tool's response."
    )


def _reference_row() -> DeepAgentTemplate:
    """Read the reference agent 198 row fresh, to inherit its non-config columns."""
    db = SessionLocal()
    try:
        row = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 198).first()
        if row is None:
            raise SystemExit("reference agent 198 not found — run seed_all first")
        return row
    finally:
        db.close()


def _create_agent(agent_def: dict) -> int:
    config = _build_config(agent_def)
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        # Idempotency: skip if an agent with this name already exists.
        existing = (
            db.query(DeepAgentTemplate)
            .filter(DeepAgentTemplate.name == agent_def["name"])
            .first()
        )
        if existing is not None:
            print(f"  '{agent_def['name']}' already exists (id={existing.id}) — skipping")
            return existing.id

        # Inherit the non-config metadata columns from agent 198 — those
        # defaults (backend_config, guardrails_config, middleware_config, etc.)
        # are required by the API response model.
        ref = _reference_row()

        row = DeepAgentTemplate(
            name=agent_def["name"],
            description=agent_def["description"],
            category=agent_def["category"],
            workspace_path=None,  # resolved + set after we know the id
            agent_docs=ref.agent_docs,
            config=config,
            middleware_config=ref.middleware_config,
            subagents_config=ref.subagents_config,
            backend_config=ref.backend_config,
            guardrails_config=ref.guardrails_config,
            export_settings=ref.export_settings,
            usage_count=0,
            last_used_at=None,
            version=1,
            is_public=True,  # so the agent shows up in the default studio list
            is_community=False,
            created_at=now,
            updated_at=now,
            lock_version=0,
        )
        db.add(row)
        db.flush()  # populate row.id
        workspace = _resolve_workspace(row.id)
        row.workspace_path = workspace
        row.config["system_prompt"] = _build_resolved_system_prompt(agent_def, row.id, workspace)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        print(f"  created '{row.name}' id={row.id} workspace={workspace}")
        return row.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    print("Creating agents that wrap the advanced LangGraph tools...")
    for agent_def in AGENT_DEFS:
        _create_agent(agent_def)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
