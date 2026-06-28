#!/usr/bin/env python3
"""
graphindex_builder_template.py — Phase 9 / Step L (Builder template)

A langconfig-importable DeepAgent template that recreates the
`graphindex_build_langgraph` builder as a configured agent. This makes
it appear in the langconfig Agent Library and Studio's deep agent
dropdown.

Why this exists
---------------

The CLI in `phase9/graphindex_build_langgraph.py` is a standalone
LangGraph 3-node StateGraph (parse_intent → execute_action → format_response).
This template exposes the same logic as a langconfig DeepAgent so a
user can:

  1. Use it in chat (with thread persistence via the runtime).
  2. Drag it onto the Studio canvas as a single node.
  3. Edit it like any other agent (swap model, change prompt, etc).

Agent structure
---------------

  - name: graphindex_builder
  - category: build
  - use_deepagents: false      → simple create_react_agent path
                                  (matches graphindex_build_langgraph philosophy:
                                   atomic tool calls, no deep subagent)
  - native_tools:
      - graphindex_ingest
      - graphindex_rebuild_one
      - graphindex_rebuild_project
      - graphindex_show
  - system_prompt: instructs the LLM to choose among the 4 build actions
  - no subagents, no skills, no middleware (keep it simple)

Why NOT graphindex_chat_template's `tools` field?
-------------------------------------------------

`graphindex_chat_template.py` uses the `tools` field, which is
read by the langconfig **import endpoint** but NOT by the runtime —
the runtime reads `native_tools` (see
backend/core/agents/factory.py:271). So an agent imported via
`POST /api/deepagents/import` ends up with `tools: [...]` but
empty `native_tools`, and the runtime can't find the tools.

For this template we use `native_tools` directly and POST to
`POST /api/deepagents/` (the create endpoint) which accepts a full
`DeepAgentConfig` with `native_tools` populated.

Compare
-------

  graphindex_chat_template.py    DeepAgent (use_deepagents: true),
                                 subagent delegation, complex chat
  graphindex_builder_template.py Simple (use_deepagents: false),
                                 4 atomic tools, build operations

CLI
---

  --print    Print the template as JSON
  --create   POST to /api/deepagents/ to create the agent
  --validate Validate the template against DeepAgentConfig schema
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict

# Repo + backend path resolution (consistent with other phase9 scripts)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))


# ===========================================================================
# System prompt for the builder agent
# ===========================================================================

SYSTEM_PROMPT = """\
You are the **graphindex_builder** agent. You help the user maintain the
document graph index for their project.

You have 4 tools, each handling ONE build operation:

  1. graphindex_ingest(file_path, project_id=None, target_dir=None)
       - Add a new file to the graph index.
       - Use when the user wants to: ingest, add, include, process, import a file.

  2. graphindex_rebuild_one(name, project_id=None)
       - Re-enrich ONE existing document.
       - Use when the user wants to: rebuild, refresh, re-enrich a specific doc.

  3. graphindex_rebuild_project(project_id=None)
       - Re-enrich EVERY document in the project.
       - Use when the user wants to: rebuild all, refresh project, re-enrich everything.
       - WARN the user: this is slow (1 LLM call per doc, ~15s each).

  4. graphindex_show(name, project_id=None)
       - Show one document's metadata (about, supported_queries, out_of_scope, etc).
       - Use when the user wants to: see, inspect, show, "what's in" a doc.

CRITICAL RULES:

  1. ALWAYS use a tool. NEVER fabricate actions or document names.
  2. Confirm parameters before calling:
     - ingest: need file_path
     - rebuild_one / show: need document name (use list_docs first if unsure)
     - rebuild_project: no params
  3. After tool execution, summarize the result for the user:
     - For ingest: file added, hash, target, enrichment summary
     - For rebuild: which doc(s) updated, timing
     - For show: present about/supports/out_of_scope nicely
  4. NEVER delete documents; you only add (ingest) or update (rebuild) or inspect (show).
  5. If the user asks a content question (not a build operation), redirect them to
     the graphindex_chat agent.

Output language matches the query (English or Chinese).
"""


# ===========================================================================
# Template builder
# ===========================================================================

def build_builder_template(
    name: str = "graphindex_builder",
    description: str = (
        "Phase 9 graphindex builder: ingests new files, rebuilds enrichment "
        "metadata, and inspects documents. 4 native tools (ingest, rebuild_one, "
        "rebuild_project, show). Simple create_react_agent path (use_deepagents=false)."
    ),
    category: str = "build",
    model: str = "minimax-m3",
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """Build the full DeepAgentConfig for the graphindex_builder agent.

    Returns:
        A dict matching the .langconfig format (with version + export_type
        + agent envelope) AND also directly compatible with
        `POST /api/deepagents/` which expects {name, description, category, config}.
    """
    return {
        "version": "1.0",
        "export_type": "deepagent",
        "name": name,
        "description": description,
        "category": category,
        "config": {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_effort": "low",
            "system_prompt": SYSTEM_PROMPT,
            "tools": [
                # Legacy `tools` field (kept for compat with the import endpoint)
                "graphindex_ingest",
                "graphindex_rebuild_one",
                "graphindex_rebuild_project",
                "graphindex_show",
            ],
            "native_tools": [
                # Runtime reads THIS field (not `tools`).
                "graphindex_ingest",
                "graphindex_rebuild_one",
                "graphindex_rebuild_project",
                "graphindex_show",
            ],
            "mcp_tools": [],
            "cli_tools": [],
            "custom_tools": [],
            # KEY: use the simple create_react_agent path, not deepagent.
            # Matches graphindex_build_langgraph.py philosophy (atomic tool calls).
            "use_deepagents": False,
            "enable_compiled_subagents": False,
            "use_local_sandbox": False,
            "middleware": [],
            "subagents": [],
            "backend": {
                "type": "state",
                "config": {},
                "mappings": None,
            },
            "guardrails": {
                "interrupts": {},
                "token_limits": {
                    "max_total_tokens": 100000,
                    "eviction_threshold": 80000,
                    "summarization_threshold": 60000,
                },
                "enable_auto_eviction": True,
                "enable_summarization": True,
                "long_term_memory": False,
            },
            "skills": [],
            "interrupt_before": None,
            "interrupt_after": None,
            "export_format": "standalone",
            "include_chat_ui": True,
            "include_docker": False,
        },
    }


# ===========================================================================
# API helpers
# ===========================================================================

DEFAULT_API_BASE = os.getenv("LANGCONFIG_API", "http://localhost:8765")


def _http_json(url: str, method: str = "GET", body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Simple JSON HTTP helper (no extra deps)."""
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ===========================================================================
# CLI
# ===========================================================================

def cmd_print() -> int:
    """Print the template JSON to stdout."""
    template = build_builder_template()
    print(json.dumps(template, ensure_ascii=False, indent=2))
    return 0


def cmd_create(api_base: str = DEFAULT_API_BASE, name: str | None = None) -> int:
    """Create the agent via POST /api/deepagents/."""
    template = build_builder_template(
        **({"name": name} if name else {}),
    )

    # POST /api/deepagents/ expects: {name, description, category, config}
    body = {
        "name": template["name"],
        "description": template["description"],
        "category": template["category"],
        "config": template["config"],
    }
    url = f"{api_base.rstrip('/')}/api/deepagents/"

    print(f"🛠  Creating agent via {url}")
    print(f"   name: {body['name']}")
    print(f"   category: {body['category']}")
    print(f"   use_deepagents: {body['config']['use_deepagents']}")
    print(f"   native_tools: {body['config']['native_tools']}")
    print()

    try:
        result = _http_json(url, method="POST", body=body)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8") if e.fp else ""
        print(f"  ✗ HTTP {e.code} {e.reason}")
        print(f"  {body_text}")
        return 1

    print(f"✅ Created agent: id={result.get('id')} name={result.get('name')}")
    print(f"   description: {result.get('description')}")
    return 0


def cmd_validate() -> int:
    """Validate the template against DeepAgentConfig schema (if backend importable)."""
    template = build_builder_template()

    try:
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from models.deep_agent import DeepAgentConfig  # type: ignore

        cfg = DeepAgentConfig(**template["config"])
        print(f"✅ Template config is valid DeepAgentConfig")
        print(f"   model: {cfg.model}")
        print(f"   tools ({len(cfg.tools or [])}): {cfg.tools}")
        print(f"   native_tools ({len(cfg.native_tools or [])}): {cfg.native_tools}")
        print(f"   use_deepagents: {cfg.use_deepagents}")
        print(f"   subagents: {len(cfg.subagents or [])}")
        return 0
    except ImportError as e:
        print(f"  ⚠ Cannot import DeepAgentConfig (backend not on path): {e}")
        print("  Falling back to JSON-level validation")
    except Exception as e:
        print(f"  ✗ Schema validation failed: {e}")
        return 1

    # JSON-level checks
    cfg = template["config"]
    if cfg["use_deepagents"]:
        print("  ⚠ use_deepagents is True; for builder we want False")
        return 1
    if not cfg["native_tools"]:
        print("  ⚠ native_tools is empty; runtime can't find tools")
        return 1
    if "graphindex_ingest" not in cfg["native_tools"]:
        print("  ✗ missing graphindex_ingest in native_tools")
        return 1
    print("  ✓ JSON-level checks pass")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="graphindex_builder agent template (langconfig .langconfig format)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python graphindex_builder_template.py --print
  python graphindex_builder_template.py --validate
  python graphindex_builder_template.py --create
  python graphindex_builder_template.py --create --name my_custom_builder
""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", action="store_true",
                       help="print the template as JSON")
    group.add_argument("--create", action="store_true",
                       help="POST to /api/deepagents/ to create the agent")
    group.add_argument("--validate", action="store_true",
                       help="validate against DeepAgentConfig schema")
    parser.add_argument("--name", metavar="NAME", default=None,
                        help="custom agent name (only for --create)")
    parser.add_argument("--api-base", metavar="URL", default=DEFAULT_API_BASE,
                        help=f"langconfig API base (default: {DEFAULT_API_BASE})")
    args = parser.parse_args()

    if args.print:
        return cmd_print()
    if args.create:
        return cmd_create(api_base=args.api_base, name=args.name)
    if args.validate:
        return cmd_validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
