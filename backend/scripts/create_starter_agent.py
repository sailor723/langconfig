#!/usr/bin/env python
"""Create (or refresh) `prompt-lab` — the starter agent that teaches prompt control.

Why this agent exists: the fastest way to explain "the prompt controls the agent" is to let
someone change four lines and watch the answer change. Everything else about this agent is
deliberately plain — three tools, one model, one small job — so that the *only* variable is
the text.

Its `AGENTS.md` opens with a **lab** block: four rules, each independently observable, each
with the experiment to run and the change to expect. Edit one, start a new chat, do the same
task, compare. That is P2 of `docs/reference/agent-practice.md` made concrete.

Idempotent: run it again and the agent is refreshed in place, not duplicated (matched by
name). Safe on any install — it only touches its own row.

Usage::

    cd backend
    .venv/bin/python scripts/create_starter_agent.py            # create or refresh
    .venv/bin/python scripts/create_starter_agent.py --delete   # remove it again
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402

NAME = "prompt-lab"

#: Three tools on purpose: enough to read an upload and write a deliverable, few enough that
#: the tool list does not compete with the instructions (see P7 in the practice guide).
NATIVE_TOOLS = ["ls", "read_any_file", "save_document"]

SYSTEM_PROMPT = """You are prompt-lab, a small agent that demonstrates one thing: behaviour
comes from these instructions, not from the model.

Do the user's task, following AGENTS.md exactly. If a rule and the request conflict, follow the
rule and say so."""

LAB_AGENTS_MD = """# prompt-lab

Three tools, one job: show that the rules below control the behaviour.
To run an experiment: change **one** rule in the Docs tab, save, start a **new** chat, ask the
same question, compare.

## Rules

- **R1 Shape** — answer in exactly three lines: `Conclusion:` / `Because:` / `Next:`. No tables.
- **R2 Length** — the whole answer fits in 40 words.
- **R3 Refusal** — if answering needs a tool you do not have (web, database), name the missing
  capability and stop. Never estimate or answer from memory as if you had checked.
- **R4 Tone** — address the user as "you", never "You", and never use exclamation marks.

## Experiments

- **R3 (run this one twice):** ask "what did our website traffic look like last month?" → it
  names the missing capability. Delete R3, run it again → a confident paragraph about numbers
  nobody measured. That difference is why refusal rules exist.
- **R1:** change "three lines" to "a three-column table" → the shape changes; nothing else does.
- **R2:** change 40 to 300 → the answer grows.
- **R4:** allow exclamation marks → visible in one line.

## Workspace

- **Workspace**: {{workspace_root}}

Deliverables go in `generated/`; uploads are read from `upload/`; `other/` is scratch. Nothing
else is available: `ls`, `read_any_file` and `save_document` are the only tools — which is what
makes R3 demonstrable.
"""

LAB_CLAUDE_MD = """# prompt-lab — CLAUDE.md

Mirror of AGENTS.md: four rules (shape, length, refusal, tone). Change one, new chat, same
question, compare. Tools: `ls`, `read_any_file`, `save_document` — nothing else.

- **Workspace**: {{workspace_root}}
"""


def _config() -> dict:
    return {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": 8000,
        "reasoning_effort": "low",
        "modalities": None,
        "tools": [],
        "native_tools": NATIVE_TOOLS,
        "cli_tools": [],
        "custom_tools": [],
        "middleware": [],
        "skills": [],
        "subagents": [],
        "use_deepagents": False,
        "use_local_sandbox": False,
        "use_phase9_graphindex": False,
        "enable_default_tools": False,
        "enable_compiled_subagents": False,
        "disable_memory_middleware": False,
        "export_format": "standalone",
        "include_chat_ui": True,
        "include_docker": False,
        "backend": {"type": "state", "config": {}, "mappings": None},
        "guardrails": {
            "interrupts": {},
            "token_limits": {
                "max_total_tokens": 60000,
                "eviction_threshold": 48000,
                "summarization_threshold": 36000,
            },
            "enable_auto_eviction": True,
            "enable_summarization": True,
            "long_term_memory": False,
        },
        "system_prompt": SYSTEM_PROMPT,
    }


def upsert(db, name: str = NAME) -> int:
    from models.deep_agent import DeepAgentTemplate

    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == name).first()
    created = agent is None
    if created:
        agent = DeepAgentTemplate(
            name=name,
            description="Starter agent for learning prompt control: four lab rules, three tools.",
            category="Custom",
            config=_config(),
            middleware_config=[],
            subagents_config=[],
            backend_config={"type": "state", "config": {}, "mappings": None},
            guardrails_config={},
            version="1.0.0",
            is_public=True,
            is_community=False,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
    else:
        cfg = dict(agent.config or {})
        cfg.update(_config())
        agent.config = cfg
        agent.description = "Starter agent for learning prompt control: four lab rules, three tools."
        db.commit()

    # Bake the identity into the prompt and the docs, exactly as the create endpoint does —
    # writing the row by hand skips that step, and an agent with an unbaked prompt tells the
    # model the wrong workspace.
    from core.agents.identity import rebake_agent_identity
    from services.workspace_manager import WorkspaceManager, get_workspace_manager

    manager = get_workspace_manager()
    workspace_root = str(manager.resolve_agent_workspace(
        agent, None, vault_key=None, agent_key=WorkspaceManager.agent_vault_key(db, agent),
    ))

    values = {"workspace_root": workspace_root, "agent_id": agent.id, "agent_name": name}
    docs = {
        "AGENTS.md": LAB_AGENTS_MD.replace("{{workspace_root}}", workspace_root)
                                 .replace("{{agent_id}}", str(agent.id))
                                 .replace("{{agent_name}}", name),
        "CLAUDE.md": LAB_CLAUDE_MD.replace("{{workspace_root}}", workspace_root),
    }
    agent.agent_docs = docs
    db.commit()

    rebake_agent_identity(agent, workspace_root)
    db.commit()

    # Materialize the docs so the Files panel and file-reading consumers see them.
    root = Path(workspace_root)
    (root / "generated").mkdir(parents=True, exist_ok=True)
    (root / "upload").mkdir(parents=True, exist_ok=True)
    for filename, content in docs.items():
        (root / filename).write_text(content, encoding="utf-8")

    print(f"  {'created' if created else 'refreshed'} {name} (id={agent.id})")
    print(f"  workspace: {workspace_root}")
    print(f"  tools    : {', '.join(NATIVE_TOOLS)}")
    return agent.id


def delete(db, name: str = NAME) -> int:
    from sqlalchemy import text
    from models.deep_agent import DeepAgentTemplate
    from services.agent_cleanup import remove_agent_workspaces

    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == name).first()
    if agent is None:
        print(f"  {name} does not exist")
        return 1
    # Workspace first, same order as the delete endpoint: a failed sweep after the row is
    # gone would leave unattributable directories.
    summary = remove_agent_workspaces(agent)
    db.execute(text("DELETE FROM chat_sessions WHERE agent_id = :i"), {"i": agent.id})
    db.delete(agent)
    db.commit()
    print(f"  deleted {name}; {len(summary['dirs'])} workspace dir(s) moved to the trash")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or refresh the prompt-lab starter agent.")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--name", default=NAME,
                        help="agent name (default: prompt-lab); a test uses its own so it "
                             "never deletes the real starter agent")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.delete:
            return delete(db, args.name)
        agent_id = upsert(db, args.name)
        print(f"\n  next: open {args.name} in the UI, run one experiment from its lab section,")
        print("        then read docs/reference/agent-practice.md §P2.")
        return 0 if agent_id else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
