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

SYSTEM_PROMPT = """You are prompt-lab, a small agent used to demonstrate that behaviour comes
from the prompt and not from the model.

Your job: take a request from the user and answer it, following the rules in your AGENTS.md
exactly. When the rules and the user's request conflict, follow the rules and say so.

If the user asks what you are for, explain in one sentence that changing the rules in the Docs
tab changes your behaviour immediately, and invite them to try.
"""

LAB_AGENTS_MD = """# prompt-lab

An agent whose whole purpose is to show that the prompt — these rules — controls the
behaviour. Everything else about it is deliberately minimal: three tools, one model, one
small job.

## Lab — four rules you can change

Each rule below is independently observable. To run an experiment: edit **one** rule in the
Docs tab, save, start a **new** chat, ask the same question again, and compare. A change you
cannot see did not take effect.

### R1 — output shape

- Answer in **exactly three lines**, prefixed `Conclusion:`, `Because:`, `Next:`. No tables,
  no headings, no extra prose.

*Experiment:* ask "summarise our sales trend". Then change `three lines` to `a table with three
columns`. The answer's shape changes immediately; nothing else about the agent did.

### R2 — length budget

- The whole answer must fit in **60 Chinese characters / 40 words**, including the prefixes.

*Experiment:* raise it to 300 and watch the answer grow. Then put it back — most "the model is
verbose" complaints are a length budget you never wrote.

### R3 — the refusal rule (the important one)

- If answering needs a tool you do not have (web search, database, file upload), say which
  capability is missing and **stop**. Never estimate, never answer from memory as if you had
  checked.

*Experiment:* ask "what did our site's traffic look like last month?" — an agent with this rule
names the missing capability. Delete the rule and run it again: it will produce a plausible
paragraph. That difference is the entire reason this rule exists.

### R4 — tone, visible in one line

- Address the user as "you" (你), never "您". Never use exclamation marks.

*Experiment:* ask it to greet a new colleague. Then flip 你 → 您 and add an exclamation-mark
ban or allowance. Tone rules are the cheapest way to prove the prompt is live.

## How to run an experiment

1. Change **one** rule. Two changes at once cannot be attributed.
2. Save the Docs tab.
3. **New chat** — a running conversation keeps the instructions it started with.
4. Ask the same question as before.
5. Decide: did the behaviour change? If not, the rule is vague, buried, or contradicted by
   another rule — sharpen it (see `docs/reference/agent-practice.md`, P2).

## What this agent cannot do

`ls`, `read_any_file` and `save_document` are its only tools. It has no web access, no
database, and no way to run shell commands — which makes R3 demonstrable rather than
theoretical.

## Workspace

- **Workspace**: {{workspace_root}}

Deliverables go in `generated/`; uploads are read from `upload/`; `other/` is scratch.
"""

LAB_CLAUDE_MD = """# prompt-lab — CLAUDE.md

Mirror of AGENTS.md; see that file for the lab rules.

- **Workspace**: {{workspace_root}}
- Four lab rules (R1 output shape, R2 length, R3 refusal, R4 tone). Change one, new chat,
  same question, compare.
- Tools: `ls`, `read_any_file`, `save_document` — nothing else. That is why R3 (refusal) is
  demonstrable.
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


def upsert(db) -> int:
    from models.deep_agent import DeepAgentTemplate

    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == NAME).first()
    created = agent is None
    if created:
        agent = DeepAgentTemplate(
            name=NAME,
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

    values = {"workspace_root": workspace_root, "agent_id": agent.id, "agent_name": NAME}
    docs = {
        "AGENTS.md": LAB_AGENTS_MD.replace("{{workspace_root}}", workspace_root)
                                 .replace("{{agent_id}}", str(agent.id))
                                 .replace("{{agent_name}}", NAME),
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

    print(f"  {'created' if created else 'refreshed'} {NAME} (id={agent.id})")
    print(f"  workspace: {workspace_root}")
    print(f"  tools    : {', '.join(NATIVE_TOOLS)}")
    return agent.id


def delete(db) -> int:
    from sqlalchemy import text
    from models.deep_agent import DeepAgentTemplate
    from services.agent_cleanup import remove_agent_workspaces

    agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == NAME).first()
    if agent is None:
        print(f"  {NAME} does not exist")
        return 1
    # Workspace first, same order as the delete endpoint: a failed sweep after the row is
    # gone would leave unattributable directories.
    summary = remove_agent_workspaces(agent)
    db.execute(text("DELETE FROM chat_sessions WHERE agent_id = :i"), {"i": agent.id})
    db.delete(agent)
    db.commit()
    print(f"  deleted {NAME}; {len(summary['dirs'])} workspace dir(s) moved to the trash")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or refresh the prompt-lab starter agent.")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.delete:
            return delete(db)
        agent_id = upsert(db)
        print(f"\n  next: open {NAME} in the UI, run one experiment from its lab section,")
        print("        then read docs/reference/agent-practice.md §P2.")
        return 0 if agent_id else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
