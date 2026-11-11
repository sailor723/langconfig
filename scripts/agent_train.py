#!/usr/bin/env python
"""Train an in-app agent from a declarative spec instead of a one-off Python script.

An agent is a row in `deep_agent_templates` plus two instructions docs plus a skill list plus a
guardrail map — and every "training" session so far rewrote that row with an ad-hoc script, which
means the change could not be reviewed, replayed, or diffed. This makes the spec the source and
the row the compiled output:

    backend/.venv/bin/python scripts/agent_train.py --spec backend/agents/table-builder.yaml --dry-run
    backend/.venv/bin/python scripts/agent_train.py --spec backend/agents/table-builder.yaml
    backend/.venv/bin/python scripts/agent_train.py --spec backend/agents/table-builder.yaml --check

What it refuses, because each of these shipped and then failed at runtime:

* a tool name that is not in `custom_tools` (a name in `native_tools` that nothing supplies is
  silently absent from the agent's toolset — measured: `glob` sat in the config and was never
  bound, and the agent reported 「我没有列目录的工具」);
* a skill id with no `SKILL.md` on disk (the registry serves files; a DB-only skill is
  unreachable, and the seed guard reads it as drift);
* a prompt that already carries a machine tail (`## Identity`) — the tail is rebuilt from the row
  on every turn, so a hand-written one goes stale and duplicates.

`--check` is the CI-facing half: it compares the spec against the stored row and exits 1 on any
difference, so "the agent was retrained by hand" cannot pass unnoticed.

Exit codes: 0 ok (written, or --check matched), 1 difference/validation failure, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SPEC_KEYS = {
    "name", "description", "category", "prompt", "prompt_file", "agents_md", "agents_md_file",
    "claude_md", "claude_md_file", "model", "temperature", "reasoning_effort", "max_tokens",
    "recursion_limit", "use_deepagents", "use_local_sandbox", "native_tools", "skills",
    "interrupts", "version",
}


def load_spec(path: Path) -> dict:
    import yaml

    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise SystemExit(f"unknown spec keys in {path}: {sorted(unknown)}; known: {sorted(SPEC_KEYS)}")
    if not spec.get("name"):
        raise SystemExit(f"{path}: `name` is required (it is how the row is found)")
    for inline, filename in (("prompt", "prompt_file"), ("agents_md", "agents_md_file"),
                             ("claude_md", "claude_md_file")):
        if inline in spec and filename in spec:
            raise SystemExit(f"{path}: give either `{inline}` or `{filename}`, not both")
        if filename in spec:
            target = path.parent / spec[filename]
            if not target.is_file():
                raise SystemExit(f"{path}: {filename} points at {target}, which does not exist")
            spec[inline] = target.read_text(encoding="utf-8")
    if not spec.get("prompt", "").strip():
        raise SystemExit(f"{path}: the agent needs a prompt (inline `prompt` or `prompt_file`)")
    return spec


# Names the deepagents SDK's FilesystemMiddleware can supply without a `custom_tools` row. They are
# accepted with a warning rather than a pass, because whether they are BOUND depends on the backend:
# `glob` sat in an agent's config, was dropped by the platform's fs-collision rule, and the agent
# reported 「我没有列目录的工具」. A platform tool such as `list_files` does not have that exposure.
SDK_FS_TOOLS = {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "delete", "execute"}


def validate_against_platform(db, spec: dict) -> tuple:
    """(errors, warnings). An error is a name the agent will not have; a warning is one it may not."""
    from models.custom_tool import CustomTool
    from core.skills.loader import SkillLoader

    problems, warnings = [], []
    tools = set(spec.get("native_tools") or [])
    if tools:
        known = {row.tool_id for row in db.query(CustomTool).all() if getattr(row, "tool_id", None)}
        missing = sorted(t for t in tools if t not in known and t not in SDK_FS_TOOLS)
        sdk_only = sorted(t for t in tools if t not in known and t in SDK_FS_TOOLS)
        if missing:
            known_list = ", ".join(sorted(known))[:600]
            problems.append(f"native_tools that nothing supplies: {missing}\n  (catalogue: {known_list})")
        if sdk_only:
            warnings.append(
                f"{sdk_only} come from the deepagents SDK, not the catalogue — binding depends on the "
                f"backend (the platform drops native fs tools when a disk backend is active). "
                f"Prefer a platform tool when one exists (e.g. list_files over glob).")

    skills = spec.get("skills") or []
    if skills:
        root = BACKEND / "skills" / "builtin"
        on_disk = {p.name for p in root.iterdir() if (p / "SKILL.md").is_file()} if root.is_dir() else set()
        missing = sorted(s for s in skills if s not in on_disk)
        if missing:
            problems.append(f"skills with no SKILL.md under backend/skills/builtin: {missing}")

    prompt = spec.get("prompt", "")
    if "## Identity" in prompt:
        problems.append("the prompt already contains `## Identity` — the machine tail is rebuilt from "
                        "the row on every turn; keep the tail out of the spec")
    return problems, warnings


def build_config(spec: dict) -> dict:
    """The row's `config` JSON, from the spec (the machine tail is added later, per workspace)."""
    from models.deep_agent import create_default_guardrails_config

    guardrails = create_default_guardrails_config(use_deepagents=bool(spec.get("use_deepagents", True)))
    guardrails.interrupts = dict(spec.get("interrupts") or {})
    return {
        "model": spec.get("model") or "deepseek-v4-pro",
        "temperature": float(spec.get("temperature", 0.2)),
        "reasoning_effort": spec.get("reasoning_effort"),
        "max_tokens": int(spec.get("max_tokens", 4000)),
        "recursion_limit": int(spec.get("recursion_limit", 60)),
        "use_deepagents": bool(spec.get("use_deepagents", True)),
        "use_local_sandbox": bool(spec.get("use_local_sandbox", False)),
        "native_tools": list(spec.get("native_tools") or []),
        "skills": list(spec.get("skills") or []),
        "guardrails": guardrails.model_dump(),
        "tools": [], "custom_tools": [], "middleware": [], "subagents": [], "plugins": [],
        "cli_tools": [], "include_chat_ui": True,
    }


def build_docs(spec: dict) -> dict:
    docs = {}
    if spec.get("agents_md"):
        docs["AGENTS.md"] = spec["agents_md"]
    if spec.get("claude_md"):
        docs["CLAUDE.md"] = spec["claude_md"]
    return docs


def summarise(config: dict, previous: dict | None) -> list:
    """Human-readable diff against the previous row (empty list = nothing changed)."""
    lines = []
    if previous is None:
        lines.append("  (new agent)")
    keys = ("model", "temperature", "max_tokens", "recursion_limit", "use_deepagents",
            "use_local_sandbox", "native_tools", "skills")
    for key in keys:
        before = None if previous is None else previous.get(key)
        after = config.get(key)
        if before != after:
            lines.append(f"  {key}: {before!r} -> {after!r}")
    if previous is not None:
        before_int = (previous.get("guardrails") or {}).get("interrupts")
        after_int = (config.get("guardrails") or {}).get("interrupts")
        if before_int != after_int:
            lines.append(f"  interrupts: {before_int!r} -> {after_int!r}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spec", required=True, type=Path, help="YAML/JSON spec describing the agent")
    ap.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 if the stored row differs from the spec")
    ap.add_argument("--workspace", help="workspace root to bake into the prompt tail (default: resolved)")
    args = ap.parse_args()

    try:
        from db.database import SessionLocal
        from models.deep_agent import DeepAgentTemplate
        from core.agents.identity import _strip_identity_block, build_identity_system_prompt
        from services.workspace_manager import get_workspace_manager
    except Exception as exc:                                   # pragma: no cover - env dependent
        print(f"cannot import the platform ({exc}); run with backend/.venv/bin/python", file=sys.stderr)
        return 2

    spec = load_spec(args.spec)
    db = SessionLocal()
    try:
        problems, warnings = validate_against_platform(db, spec)
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        if problems:
            print(f"{args.spec} does not validate:", file=sys.stderr)
            for p in problems:
                print("  -", p, file=sys.stderr)
            return 1

        config = build_config(spec)
        docs = build_docs(spec)
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == spec["name"]).first()
        previous = dict(agent.config) if agent and isinstance(agent.config, dict) else None
        changes = summarise(config, previous)

        prompt_body = _strip_identity_block(spec["prompt"]).strip()
        mgr = get_workspace_manager()
        if agent is not None:
            workspace = args.workspace or str(mgr.resolve_agent_workspace(
                agent, None, vault_key=None, agent_key=mgr.agent_vault_key(db, agent)))
            agent_id = agent.id
        else:
            workspace = args.workspace or ""
            agent_id = None

        if args.check:
            if agent is None:
                print(f"MISSING: no agent named {spec['name']!r}", file=sys.stderr)
                return 1
            stored_prompt = _strip_identity_block((previous or {}).get("system_prompt", "")).strip()
            prompt_differs = stored_prompt != prompt_body
            # Compare docs by content, not by trailing whitespace: exporting a doc to a file and
            # reading it back adds a newline, which is not drift.
            def _norm(d: dict) -> dict:
                return {k: (v or "").strip() for k, v in (d or {}).items()}
            docs_differ = _norm(agent.agent_docs) != _norm(docs)
            if changes or prompt_differs or docs_differ:
                print(f"DRIFT: {spec['name']} does not match {args.spec}")
                for line in changes:
                    print(line)
                if prompt_differs:
                    print(f"  prompt: {len(stored_prompt)} chars stored vs {len(prompt_body)} in the spec")
                if docs_differ:
                    print(f"  docs: stored {sorted((agent.agent_docs or {}))} vs spec {sorted(docs)}")
                return 1
            print(f"OK: {spec['name']} (id {agent.id}) matches {args.spec.name}")
            return 0

        if not changes and not (previous is None):
            print(f"nothing to change for {spec['name']} (id {agent.id})")
            return 0
        print(f"{'would update' if previous is not None else 'would create'} {spec['name']}:")
        for line in changes or ["  (no config change)"]:
            print(line)

        if args.dry_run:
            print("dry run: nothing written")
            return 0

        if agent is None:
            agent = DeepAgentTemplate(name=spec["name"], description=spec.get("description") or "",
                                      category=spec.get("category") or "Analysis", config=config,
                                      middleware_config={}, subagents_config=[],
                                      backend_config={"type": "state", "config": {}, "mappings": None},
                                      guardrails_config=config["guardrails"], export_settings=None)
            db.add(agent)
            db.commit()
            db.refresh(agent)
            workspace = args.workspace or str(mgr.resolve_agent_workspace(
                agent, None, vault_key=None, agent_key=mgr.agent_vault_key(db, agent)))

        final = dict(config)
        final["system_prompt"] = build_identity_system_prompt(prompt_body, agent.id, workspace, docs)
        agent.description = spec.get("description") or agent.description
        agent.category = spec.get("category") or agent.category
        if spec.get("version"):
            agent.version = str(spec["version"])
        agent.guardrails_config = final["guardrails"]
        agent.agent_docs = docs
        agent.config = final
        db.commit()
        print(f"written: {spec['name']} (id {agent.id}), prompt {len(final['system_prompt'])} chars, "
              f"workspace {workspace or '(unresolved)'}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
