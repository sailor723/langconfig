#!/usr/bin/env python
"""Inspect what a DeepAgent build actually produces — the study's probe, kept in-tree.

Three questions this answers without reading any SDK source:

1. What does our factory pass to ``deepagents.create_deep_agent``?
2. What middleware stack does the SDK then hand to LangChain's ``create_agent``?
3. What tools end up dispatchable in the compiled graph, and what does the final
   system prompt look like?

Usage (from ``backend/``):

    .venv/bin/python scripts/inspect_agent_build.py 213
    .venv/bin/python scripts/inspect_agent_build.py 209 --prompt

Nothing is written to the DB. Workspace folders are created if missing, exactly
as a chat build would create them.

Why a script and not a test: the three probes monkeypatch
``deepagents.create_deep_agent`` and ``deepagents.graph.create_agent`` in-process,
which is only meaningful for a single build at a time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_config(agent_id: int):
    from sqlalchemy import text

    from db.database import SessionLocal
    from models.deep_agent import DeepAgentConfig

    db = SessionLocal()
    try:
        raw = db.execute(
            text("SELECT config FROM deep_agent_templates WHERE id=:i"), {"i": agent_id}
        ).scalar()
    finally:
        db.close()
    if raw is None:
        raise SystemExit(f"no deep_agent_templates row with id={agent_id}")
    return DeepAgentConfig(**(raw if isinstance(raw, dict) else json.loads(raw)))


def _runtime_tools(agent) -> list[str]:
    """Tool names reachable from the compiled graph's tool node."""
    node = agent.nodes.get("tools")
    seen: set[int] = set()
    names: list[str] = []

    def walk(obj, depth: int = 0) -> None:
        if obj is None or depth > 3:
            return
        by_name = getattr(obj, "tools_by_name", None)
        if isinstance(by_name, dict):
            names.extend(by_name)
        for attr in ("bound", "func", "node", "runnable"):
            child = getattr(obj, attr, None)
            if child is not None and id(child) not in seen:
                seen.add(id(child))
                walk(child, depth + 1)

    walk(getattr(node, "bound", None) or node)
    return sorted(set(names))


async def inspect(agent_id: int, show_prompt: bool) -> None:
    config = _load_config(agent_id)

    import deepagents
    import deepagents.graph as dg

    sdk_kwargs: dict = {}
    lc_kwargs: dict = {}
    real_create_deep_agent = deepagents.create_deep_agent
    real_create_agent = dg.create_agent

    def spy_deep_agent(**kwargs):
        sdk_kwargs.clear()
        sdk_kwargs.update(kwargs)
        return real_create_deep_agent(**kwargs)

    def spy_create_agent(*args, **kwargs):
        lc_kwargs.clear()
        lc_kwargs.update(kwargs)
        return real_create_agent(*args, **kwargs)

    deepagents.create_deep_agent = spy_deep_agent
    dg.create_agent = spy_create_agent

    from services.deepagent_factory import DeepAgentFactory

    workspace_root = os.path.abspath(f"outputs/agents/agent_{agent_id}")
    agent, configured_tools, _callbacks = await DeepAgentFactory.create_deep_agent(
        config=config,
        project_id=1,
        task_id=1,
        context="inspect",
        workspace_root=workspace_root,
        agent_id=agent_id,
    )

    print("=" * 78)
    print(f"agent {agent_id} — config")
    print("=" * 78)
    print(f"  model={config.model}  temperature={config.temperature}  max_tokens={config.max_tokens}")
    print(f"  native_tools({len(config.native_tools or [])}): {config.native_tools}")
    print(f"  skills={config.skills}  plugins={config.plugins}")
    print(f"  middleware config: {[(m.type.value, m.enabled) for m in config.middleware]}")
    print(f"  subagents: {[(s.name, s.type.value) for s in config.subagents]}")
    print(f"  guardrails: {config.guardrails.model_dump() if config.guardrails else None}")
    print(f"  use_local_sandbox={config.use_local_sandbox}  "
          f"disable_memory_middleware={config.disable_memory_middleware}")

    print()
    print("=" * 78)
    print("what our factory passes to deepagents.create_deep_agent")
    print("=" * 78)
    print(f"  parameters: {sorted(sdk_kwargs)}")
    backend = sdk_kwargs.get("backend")
    inner = getattr(backend, "_backend", backend)
    print(f"  backend: {type(backend).__name__} -> {type(inner).__name__}")
    print(f"    routes={list(getattr(inner, 'routes', {}) or {})}  "
          f"default={type(getattr(inner, 'default', None)).__name__}")
    print(f"  skills sources: {sdk_kwargs.get('skills')}")
    print(f"  subagents passed: "
          f"{[s.get('name') if isinstance(s, dict) else type(s).__name__ for s in (sdk_kwargs.get('subagents') or [])] or '-'}")
    print(f"  middleware passed by us: {len(sdk_kwargs.get('middleware') or [])}")
    print(f"  interrupt_on: {sdk_kwargs.get('interrupt_on')}")

    print()
    print("=" * 78)
    print("middleware stack handed to langchain create_agent (SDK + ours)")
    print("=" * 78)
    for i, mw in enumerate(lc_kwargs.get("middleware") or []):
        tools = [getattr(t, "name", t) for t in (getattr(mw, "tools", None) or [])]
        print(f"  {i:2}. {type(mw).__name__:<42} tools={tools or '-'}")
    state_schema = lc_kwargs.get("state_schema")
    print(f"  state_schema: {getattr(state_schema, '__name__', state_schema)}")

    print()
    print("=" * 78)
    print("tools")
    print("=" * 78)
    print(f"  configured (config.native_tools -> loaded): {len(configured_tools)}")
    runtime = _runtime_tools(agent)
    print(f"  dispatchable in the compiled graph: {len(runtime)}")
    print(f"    SDK-injected (not in the editor): "
          f"{sorted(set(runtime) - {getattr(t, 'name', '') for t in configured_tools})}")
    print("    NOTE: the model sees fewer than this — the SDK strips capability-gated "
          "tools (e.g. `execute` without a sandbox) per request.")

    if show_prompt:
        print()
        print("=" * 78)
        print("final system prompt structure")
        print("=" * 78)
        prompt = sdk_kwargs.get("system_prompt") or ""
        print(f"  {len(prompt)} chars, {prompt.count(chr(10))} lines")
        for line in prompt.splitlines():
            if line.startswith("#") or line.startswith("- **"):
                print(f"    {line[:106]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_id", type=int, help="deep_agent_templates.id")
    parser.add_argument("--prompt", action="store_true", help="print the prompt outline")
    args = parser.parse_args()
    asyncio.run(inspect(args.agent_id, args.prompt))


if __name__ == "__main__":
    main()
