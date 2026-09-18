#!/usr/bin/env python3
"""
agent_creator_setup.py — build & test an "Agent Creator" DeepAgent, pure Python.

The Agent Creator is a chat-driven meta-agent (Fleet-style agent creation):
  given customer input, it designs a LangChain agent (prompt + tools + skills),
  persists it with the create_deepagent tool, and can update an existing
  agent's prompt per LangChain agent specs.

Flow (mirrors the UI's form-based creation but driven from the backend):
  1. Fix the seeded `create_deepagent` builtin row so list args work
     (its input_schema declares string, but pydantic v1 rejects a plain
     string for List[str] — we make the tool parse comma/JSON-array text).
  2. Create an `update_agent_prompt` custom tool (update prompt by agent id).
  3. Create the "Agent Creator" deepagent with templates/tools/skills from
     the database (pg_list_agents / pg_get_agent / pg_list_skills /
     pg_list_custom_tools / search_skills / create_skill + create_deepagent
     + update_agent_prompt + web_search/web_fetch).
  4. Chat test: "create agent X for requirement Y" -> expect a real agent
     row created; then test the prompt-update flow.

Usage:
    .venv/bin/python backend/scripts/agent_creator_setup.py            # full run
    .venv/bin/python backend/scripts/agent_creator_setup.py --skip-chat
    .venv/bin/python backend/scripts/agent_creator_setup.py --force    # recreate Agent Creator
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Optional

import httpx
import psycopg2

API_BASE = "http://localhost:8765"
DB_DSN = "postgresql://langconfig:langconfig_dev@localhost:5432/langconfig"
TIMEOUT = httpx.Timeout(300.0, connect=10.0)  # creator runs multiple tool calls


# =============================================================================
# 1) Fixed create_deepagent implementation (self-contained, row-embedded)
# =============================================================================

FIXED_CREATE_DEEPAGENT_CODE = '''# --- imports ---

from langchain_core.tools import InjectedToolCallId, StructuredTool, tool
import json


def _parse_list(value):
    """Accept a real list, a JSON-array string, or a comma-separated string.

    The python_function arg builder only emits primitive types (string/
    integer/number/boolean), so LLM calls arrive as plain strings. This
    normalizer handles all three shapes.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass  # not JSON — fall back to comma-splitting below
        return [x.strip() for x in text.split(",") if x.strip()]
    return [str(value)]


def create_deepagent(name: str,
                     system_prompt: str,
                     native_tools: str,
                     skills: str = "",
                     description: str = "",
                     category: str = "Custom",
                     model: str = "deepseek-chat",
                     temperature: float = 0.3) -> str:
    """Create a new DeepAgent through the SAME standard REST endpoint the DeepAgent Builder UI uses (POST /api/deepagents/).

    Use this tool when the user wants to SAVE a designed agent configuration permanently.

    Args:
        name: Agent name (e.g. 'market-research-assistant')
        system_prompt: The COMPLETE system prompt defining the agent's behavior
        native_tools: Comma-separated or JSON-array list of tool names (e.g. "web_search, web_fetch")
        skills: Comma-separated or JSON-array list of skill IDs (e.g. "web-search, text-summarizer")
        description: Short 1-2 sentence description of what the agent does
        category: Agent category (e.g. 'Research', 'Coding', 'Custom')
        model: Model name (default: 'deepseek-chat')
        temperature: Model temperature 0.0-1.0 (default: 0.3)
    """
    import httpx

    tools = _parse_list(native_tools)
    payload = {
        "name": name.strip(),
        "description": (description or "").strip(),
        "category": category or "Custom",
        "config": {
            "system_prompt": system_prompt.strip(),
            "model": model or "deepseek-chat",
            "temperature": temperature if temperature is not None else 0.3,
            "native_tools": tools,
            "cli_tools": [],
            "custom_tools": [],
            "tools": tools,
            "skills": _parse_list(skills),
            "subagents": [],
            "middleware": [
                {"type": "todo_list", "enabled": True, "config": {}},
                {"type": "filesystem", "enabled": True, "config": {}},
            ],
            "backend": {"type": "state"},
            "guardrails": {
                "enable_auto_eviction": False,
                "enable_summarization": False,
                "long_term_memory": False,
            },
            "use_deepagents": True,
        },
    }
    try:
        resp = httpx.post("http://localhost:8765/api/deepagents/", json=payload, timeout=120)
        if resp.status_code >= 400:
            return f"\\u274c Create failed ({resp.status_code}): {resp.text[:500]}"
        data = resp.json()
        return (
            f"\\u2705 Agent '{data['name']}' (id={data['id']}) created successfully!\\n\\n"
            f"Agent is now available in the DeepAgent Studio. The user can:\\n"
            f"1. Select it from the agent dropdown to see its topology\\n"
            f"2. Click 'Test' to start a conversation with it\\n"
            f"3. Click 'Edit' to modify its configuration"
        )
    except Exception as e:
        return f"\\u274c Failed to create agent: {e}"
'''


# =============================================================================
# 2) update_agent_prompt custom tool implementation
# =============================================================================

UPDATE_AGENT_PROMPT_CODE = '''# --- imports ---

from langchain_core.tools import InjectedToolCallId, StructuredTool, tool


def update_agent_prompt(agent_id: int, system_prompt: str) -> str:
    """Update the system prompt of an existing DeepAgent through the SAME standard REST endpoint the DeepAgent Editor UI uses (PUT /api/deepagents/{id}).

    Args:
        agent_id: Numeric agent id (from pg_list_agents)
        system_prompt: The new COMPLETE system prompt following LangChain agent specs
    """
    import httpx

    base = f"http://localhost:8765/api/deepagents/{agent_id}"
    try:
        # Read the full agent first so the PUT round-trips everything (the UI does the same)
        get_resp = httpx.get(base, timeout=60)
        if get_resp.status_code >= 400:
            return f"\\u274c Agent {agent_id} not found: {get_resp.text[:300]}"
        agent = get_resp.json()

        cfg = dict(agent.get("config") or {})
        cfg["system_prompt"] = system_prompt.strip()

        payload = {
            "name": agent.get("name"),
            "description": agent.get("description"),
            "category": agent.get("category"),
            "config": cfg,
            "lock_version": agent.get("lock_version"),
        }
        put_resp = httpx.put(base, json=payload, timeout=120)
        if put_resp.status_code >= 400:
            return f"\\u274c Update failed ({put_resp.status_code}): {put_resp.text[:500]}"
        return f"\\u2705 Agent '{agent.get('name')}' (id={agent_id}) system prompt updated."
    except Exception as e:
        return f"\\u274c Failed to update prompt: {e}"
'''

UPDATE_AGENT_PROMPT_ARGS = {
    "agent_id": {"type": "integer", "description": "Numeric agent id (from pg_list_agents)"},
    "system_prompt": {"type": "string", "description": "The new COMPLETE system prompt"},
}


# =============================================================================
# 3) Agent Creator definition
# =============================================================================

CREATOR_SYSTEM_PROMPT = """You are the Agent Creator — an expert at designing and building LangChain / LangGraph agents on the LangConfig platform.

YOUR JOB:
Given a customer request, design a complete agent (prompt + tools + skills) and CREATE it, so the customer can immediately chat with it.

WORKFLOW (follow on every request):
1. UNDERSTAND the requirement: the agent's role, goals, required tools, and skills.
2. RESEARCH the database before designing anything:
   - pg_list_agents — browse existing agents/templates (learn from good examples)
   - pg_get_agent   — inspect a specific agent's full config
   - pg_list_skills — find skills that fit the requirement
   - search_skills  — keyword-search for skills
   - pg_list_custom_tools — see what tools already exist
   If the requirement needs a brand-new skill that does not exist, create it with create_skill.
3. DESIGN: write a clear role-based system prompt following LangChain agent best practices (see the langchain-agents skill). Pick the right model, temperature, native tools, and skills — only use tools/skills that exist in the database.
4. CREATE with create_deepagent: pass name, system_prompt, native_tools (comma-separated), skills (comma-separated), description, category, model, temperature.
5. UPDATE (if asked): adjust an existing agent's prompt with update_agent_prompt(agent_id, system_prompt).
6. REPORT: the created agent's id and name, its tools and skills, and how to start chatting with it.

RULES:
- Never invent agent ids, tool names, or skill ids — only use what the tools return.
- Use model 'deepseek-chat' unless the customer specifies another model.
- If the request is vague or missing key details, ask ONE clarifying question instead of guessing.
- Answer in the customer's language."""

CREATOR_NAME = "Agent Creator"
CREATOR_TOOLS = [
    "create_deepagent",
    "update_agent_prompt",
    "pg_list_agents",
    "pg_get_agent",
    "pg_list_skills",
    "pg_list_custom_tools",
    "search_skills",
    "create_skill",
]


def build_creator_payload() -> Dict[str, Any]:
    """Agent Creator deepagent payload (mirrors the UI's buildConfig shape)."""
    native_tools = ["web_search", "web_fetch"]
    return {
        "name": CREATOR_NAME,
        "description": (
            "Chat-driven meta-agent: designs and creates LangChain agents from "
            "customer requirements using templates, skills, and tools in the database."
        ),
        "category": "Custom",
        "config": {
            "system_prompt": CREATOR_SYSTEM_PROMPT,
            "model": "deepseek-chat",
            "temperature": 0.3,
            "max_tokens": 4096,
            "native_tools": native_tools,
            "cli_tools": [],
            "custom_tools": CREATOR_TOOLS,
            "tools": native_tools + CREATOR_TOOLS,
            "skills": ["langchain-agents", "langconfig-builder"],
            "subagents": [],
            "middleware": [
                {"type": "todo_list", "enabled": True, "config": {}},
                {"type": "filesystem", "enabled": True, "config": {}},
            ],
            "backend": {"type": "state"},
            "guardrails": {
                "enable_auto_eviction": False,
                "enable_summarization": False,
                "long_term_memory": False,
            },
            "use_deepagents": True,
        },
    }


# =============================================================================
# DB helpers
# =============================================================================

def db_fix_create_deepagent_row() -> bool:
    """Patch the seeded `create_deepagent` row so it parses string lists."""
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, implementation_config FROM custom_tools WHERE tool_id='create_deepagent'")
            row = cur.fetchone()
            if row is None:
                print("  ! create_deepagent row not found — cannot patch")
                return False
            tool_row_id, impl = row
            impl = dict(impl or {})
            impl["code"] = FIXED_CREATE_DEEPAGENT_CODE
            impl["function_name"] = "create_deepagent"
            impl["args_schema"] = {
                "name": {"type": "string", "description": "Agent name"},
                "system_prompt": {"type": "string", "description": "The COMPLETE system prompt"},
                "native_tools": {"type": "string", "description": "Comma-separated or JSON-array tool names"},
                "skills": {"type": "string", "description": "Comma-separated or JSON-array skill IDs", "default": ""},
                "description": {"type": "string", "description": "Short description", "default": ""},
                "category": {"type": "string", "description": "Agent category", "default": "Custom"},
                "model": {"type": "string", "description": "Model name", "default": "deepseek-chat"},
                "temperature": {"type": "number", "description": "Temperature 0-1", "default": 0.3},
            }
            cur.execute(
                "UPDATE custom_tools SET implementation_config=%s WHERE id=%s",
                (json.dumps(impl), tool_row_id),
            )
    print("  ✓ create_deepagent row patched (string-list parsing)")
    return True


def db_agent_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Fetch the newest deep_agent_templates row matching `name`."""
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, category, config FROM deep_agent_templates "
                "WHERE name=%s ORDER BY id DESC LIMIT 1",
                (name,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "name": row[1], "category": row[2], "config": row[3]}


# =============================================================================
# API helpers
# =============================================================================

def _check(resp: httpx.Response, label: str) -> Dict[str, Any]:
    if resp.status_code >= 400:
        raise RuntimeError(f"{label} failed ({resp.status_code}): {resp.text[:800]}")
    return resp.json()


def ensure_update_tool(client: httpx.Client) -> None:
    """Create (or refresh) the update_agent_prompt custom tool via the standard API."""
    resp = client.get("/api/custom-tools")
    existing = _check(resp, "list custom tools")
    for t in existing:
        if t["tool_id"] == "update_agent_prompt":
            _check(client.delete(f"/api/custom-tools/{t['tool_id']}"), "delete old update_agent_prompt tool")
            print("  ✓ removed previous update_agent_prompt tool (refreshing)")
            break
    payload = {
        "tool_id": "update_agent_prompt",
        "name": "Update Agent Prompt",
        "description": (
            "Update the system prompt of an existing DeepAgent by id "
            "(find ids with pg_list_agents). Follows LangChain agent specs."
        ),
        "tool_type": "python_function",
        "template_type": "custom",
        "output_format": "string",
        "implementation_config": {
            "function_name": "update_agent_prompt",
            "code": UPDATE_AGENT_PROMPT_CODE,
            "args_schema": UPDATE_AGENT_PROMPT_ARGS,
        },
        "input_schema": {
            "type": "object",
            "properties": UPDATE_AGENT_PROMPT_ARGS,
            "required": ["agent_id", "system_prompt"],
        },
        "is_public": True,
        "created_by": "agent-creator-setup",
        "category": "agent_management",
    }
    _check(client.post("/api/custom-tools", json=payload), "create update_agent_prompt tool")
    print("  ✓ update_agent_prompt custom tool created")


def ensure_creator(client: httpx.Client, force: bool) -> int:
    """Create (or recreate) the Agent Creator deepagent; return its id."""
    agents = _check(client.get("/api/deepagents/"), "list deepagents")
    match = [a for a in agents if a.get("name") == CREATOR_NAME]
    if match and not force:
        print(f"  ✓ Agent Creator already exists (id={match[-1]['id']})")
        return match[-1]["id"]
    if match and force:
        _check(client.delete(f"/api/deepagents/{match[-1]['id']}"), "delete old Agent Creator")
        print("  ✓ deleted previous Agent Creator")
    resp = _check(client.post("/api/deepagents/", json=build_creator_payload()), "create Agent Creator")
    print(f"  ✓ Agent Creator created (id={resp['id']})")
    return resp["id"]


# =============================================================================
# Chat test
# =============================================================================

def chat(client: httpx.Client, session_id: str, message: str, label: str) -> str:
    print(f"\n  ▶ chat: {label}")
    resp = _check(client.post("/api/chat/message", json={
        "session_id": session_id,
        "message": message,
    }), f"chat: {label}")
    content = resp.get("content") or resp.get("response") or ""
    print(f"  reply ({len(content)} chars):")
    print("  " + (content[:1200].replace("\n", "\n  ")))
    return str(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build & test the Agent Creator deepagent")
    parser.add_argument("--skip-chat", action="store_true", help="Skip chat tests")
    parser.add_argument("--force", action="store_true", help="Recreate the Agent Creator agent")
    args = parser.parse_args()

    start = time.time()

    # Phase 1 — runtime fix for the seeded create_deepagent tool
    print("\n[1/3] Patch seeded create_deepagent tool")
    db_fix_create_deepagent_row()

    with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as client:
        # Phase 2 — tools + agent
        print("\n[2/3] Ensure update_agent_prompt tool + Agent Creator agent")
        ensure_update_tool(client)
        creator_id = ensure_creator(client, args.force)

        # Phase 3 — chat tests
        print("\n[3/3] Chat tests (customer input → built agent)")
        if args.skip_chat:
            print("  skipped")
            return 0

        sess = _check(client.post("/api/chat/start", json={"agent_id": creator_id}), "start chat")
        session_id = sess["session_id"]
        print(f"  session_id={session_id}")

        # Test A: create an agent from customer input
        chat(client, session_id,
             "Create a Python code review assistant. It should use the web_search tool "
             "and the code-review skill. Model deepseek-chat, temperature 0.2, "
             "category Coding. Name it 'py-code-reviewer'.",
             "customer input → create agent")

        built = db_agent_by_name("py-code-reviewer")
        if not built:
            print("\n  ✗ FAIL: 'py-code-reviewer' was NOT created in the DB")
            return 1
        cfg = built["config"] or {}
        print(f"\n  ✓ DB verify: id={built['id']} name={built['name']} category={built['category']}")
        print(f"  ✓ tools={cfg.get('native_tools')}")
        print(f"  ✓ skills={cfg.get('skills')}")
        print(f"  ✓ model={cfg.get('model')} temp={cfg.get('temperature')}")

        # Test B: update that agent's prompt (LangChain agent spec adjustment)
        chat(client, session_id,
             "Update the system prompt of py-code-reviewer to focus on security "
             "vulnerabilities first, then code style.",
             "customer input → update prompt")

        updated = db_agent_by_name("py-code-reviewer")
        new_prompt = (updated["config"] or {}).get("system_prompt", "")
        if "security" not in new_prompt.lower():
            print("\n  ✗ FAIL: system prompt was not updated (security focus missing)")
            print(f"  current prompt head: {new_prompt[:200]!r}")
            return 1
        print("\n  ✓ DB verify: system prompt updated (mentions security)")

    print(f"\n✅ AGENT CREATOR TESTS PASSED in {time.time() - start:.1f}s "
          f"(creator id={creator_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
