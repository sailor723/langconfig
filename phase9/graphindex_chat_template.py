#!/usr/bin/env python3
"""
Phase 9 / Step L0 — graphindex_chat agent template.

A langconfig-importable DeepAgent template (".langconfig" JSON format)
that recreates the `graphindex_chat` single-agent DeepAgent from
`phase9/build_graphindex_chat_agent.py`, but using the langconfig
**native tool registry** tools (the 4 graphindex_* tools) so users can
load it via `POST /api/deepagents/import` and the langconfig UI can
edit it like any other DeepAgent.

Why this exists
---------------

The single agent in `phase9/build_graphindex_chat_agent.py` is a
"reference implementation" — it hardcodes:

  - 4 specific tools (graphindex_list_docs, graphindex_search, etc.)
  - 1 system prompt (graphindex_chat prompt)
  - 1 model (minimax-m3)
  - 0 subagents

This template exposes the same thing as a langconfig DeepAgent so a
user can:

  1. Import it via the agent builder UI ("Use graphindex_chat in
     agent builder" button on the Knowledge panel).
  2. Edit it like any other agent (swap model, change system prompt,
     add/remove tools, add subagents).
  3. Save as their own derivative agent.

The .langconfig JSON format
---------------------------

A .langconfig file is the export format used by
`POST /api/deepagents/{id}/export` and accepted by
`POST /api/deepagents/import`. The shape is:

  {
    "version": "1.0",
    "export_type": "deepagent",
    "agent": {
      "name": "...",
      "description": "...",
      "category": "research",
      "model": "minimax-m3",
      "temperature": 0.0,
      "max_tokens": 8192,
      "system_prompt": "...",
      "tools": [...],
      "mcp_tools": [],
      "cli_tools": [],
      "middleware": [...],
      "subagents": [],
      "backend": { "type": "state", "config": {} },
      "guardrails": {}
    }
  }

Note: `tools` is a list of strings (tool names registered in the
langconfig native tool registry). The 4 graphindex_* tools are
already registered in `backend/tools/native_tools.py` with the same
names.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

# Repo + backend path resolution (so the same file works as a script
# and can be imported from other phase9 files).
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "phase9"))


# Reuse the same system prompt as build_graphindex_chat_agent.py, but
# mention langconfig native tools (not the phase9 @tool wrappers) so
# the user sees familiar tool names in the langconfig UI.
SYSTEM_PROMPT = """You are **graphindex_chat** — a conversational research
assistant for the user's project documents. (Phase 9 / LLM semantic routing)

You have 4 native tools (from langconfig's GraphIndex toolset, Phase 9):

  - graphindex_list_docs(project_id)         — list available doc names
  - graphindex_search(query, project_id)     — find the best primary +
                                                0-3 supporting docs
  - graphindex_load(context_doc_id)          — read a single doc's full text
  - graphindex_multi_doc_load(query, project_id)
                                              — one-shot: route + load
                                                primary + supporting

Workflow:

  1. If unsure what docs exist, call graphindex_list_docs first (cheap).
  2. To answer a question, prefer graphindex_multi_doc_load — it does
     routing + loading in one call. (Or use graphindex_search +
     graphindex_load for fine control.)
  3. Synthesize the final answer from the loaded context. Cite the
     document name and page when relevant.

If the user asks something unrelated to the project documents, say so
politely. Don't make up document names — always check the catalog.

Keep replies concise but cite your sources. Output language matches the
query.
"""


def build_graphindex_chat_template(
    name: str = "graphindex_chat",
    description: str = "LLM-semantic-routed chat with project documents (Phase 9). 4 native tools: list, search, load, multi_doc_load.",
    category: str = "research",
    model: str = "minimax-m3",
    temperature: float = 0.0,
    max_tokens: int = 8192,
) -> Dict[str, Any]:
    """Build a .langconfig-format dict for the graphindex_chat agent.

    Args:
        name: Agent name shown in the langconfig agent library.
        description: Short description for the agent card.
        category: AgentCategory enum value (research, planning, ...).
        model: Default LLM. Per step 4 of the project plan, deepseek-chat
            (minimax-m3) is the default; user can override after import.
        temperature: 0.0 for deterministic routing.
        max_tokens: 8192 for synthesis.

    Returns:
        A dict matching the .langconfig format. Pass to
        `POST /api/deepagents/import` as the `langconfig_content` field
        (json-stringified).
    """
    return {
        "version": "1.0",
        "export_type": "deepagent",
        "agent": {
            "name": name,
            "description": description,
            "category": category,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt": SYSTEM_PROMPT,
            "tools": [
                "graphindex_list_docs",
                "graphindex_search",
                "graphindex_load",
                "graphindex_multi_doc_load",
            ],
            "mcp_tools": [],
            "cli_tools": [],
            "middleware": [
                # Default middleware: TodoList (track plan), Summarization
                # (compress long context), Filesystem (read/write files
                # in workspace). Matches the deepagent default.
                {"type": "todo_list", "enabled": True, "config": {}},
                {"type": "filesystem", "enabled": True, "config": {}},
            ],
            "subagents": [],
            "backend": {
                "type": "state",
                "config": {},
            },
            "guardrails": {},
        },
    }


def to_import_payload(template: Dict[str, Any] | None = None) -> str:
    """Return a JSON string suitable for `POST /api/deepagents/import`."""
    if template is None:
        template = build_graphindex_chat_template()
    return json.dumps(template, ensure_ascii=False, indent=2)


# --- CLI entry point ------------------------------------------------------

HELP_TEXT = """\
Phase 9 / graphindex_chat agent template.

Modes:
  --print           print the .langconfig JSON to stdout
  --save FILE       save the .langconfig JSON to FILE
  --import          POST to /api/deepagents/import (requires server)
  --server URL      override base URL (default http://localhost:8000)
  --name NAME       override agent name
  --model MODEL     override default model

Examples:
  python phase9/graphindex_chat_template.py --print
  python phase9/graphindex_chat_template.py --save /tmp/graphindex_chat.langconfig
  python phase9/graphindex_chat_template.py --import
  python phase9/graphindex_chat_template.py --import --server http://localhost:8765
  python phase9/graphindex_chat_template.py --name "My Research Agent" --import
"""


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="graphindex_chat agent template (Step L0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT,
    )
    parser.add_argument("--print", action="store_true",
                        help="print the .langconfig JSON to stdout")
    parser.add_argument("--save", help="save the .langconfig JSON to FILE")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="POST to /api/deepagents/import")
    parser.add_argument("--server", default="http://localhost:8000",
                        help="base URL of the langconfig API server")
    parser.add_argument("--name", help="override agent name")
    parser.add_argument("--model", help="override default model")
    parser.add_argument("--description", help="override description")
    args = parser.parse_args(argv)

    kwargs = {}
    if args.name:
        kwargs["name"] = args.name
    if args.model:
        kwargs["model"] = args.model
    if args.description:
        kwargs["description"] = args.description

    template = build_graphindex_chat_template(**kwargs)
    payload = to_import_payload(template)

    if args.print or (not args.save and not args.do_import):
        print(payload)
        return 0

    if args.save:
        Path(args.save).write_text(payload, encoding="utf-8")
        print(f"Saved template to {args.save}")
        return 0

    if args.do_import:
        try:
            import requests
        except ImportError:
            print("ERROR: 'requests' not installed. Use --save + curl instead.")
            return 1
        url = f"{args.server.rstrip('/')}/api/deepagents/import"
        try:
            r = requests.post(
                url,
                json={"langconfig_content": payload},
                timeout=60,
            )
        except Exception as e:
            print(f"ERROR: import failed: {e}")
            return 1
        if r.status_code == 200:
            data = r.json()
            print(f"✓ Imported graphindex_chat agent (id={data.get('id')}, name={data.get('name')!r})")
            print(f"  View in agent library: GET {args.server}/api/deepagents/{data.get('id')}")
            return 0
        else:
            print(f"✗ Import failed (HTTP {r.status_code}): {r.text}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
