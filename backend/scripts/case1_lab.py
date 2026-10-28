#!/usr/bin/env python
"""case1-lab — measure whether the three "case 1" rules change anything.

Case 1 is the *generic chat* agent: no tools, no web. The claim under test is
that such an agent has almost no prompt work to do, except three boundary
behaviours:

  C1  it does not know realtime / private / current facts, and must say so
      instead of producing a well-formed number;
  C2  its default gear should be "answer", not "interview me first";
  C3  what the user already said in this conversation is a constraint.

Each rule gets one experiment with a question where the *wrong* behaviour is
tempting. If the baseline already behaves, the rule is noise and should be
deleted — that is the point of running this.

Usage::

    cd backend
    .venv/bin/python scripts/case1_lab.py --mode both    # baseline + rules
    .venv/bin/python scripts/case1_lab.py --mode rules   # only the rules build
    .venv/bin/python scripts/case1_lab.py --delete
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

BASE = "http://127.0.0.1:8765"
NAME = "case1-lab"

SYSTEM_PROMPT = """You are case1-lab, a general-purpose chat assistant.
Answer the user's questions directly."""

#: Baseline: no rules at all. Whatever the model does here is the model's own
#: default behaviour — which is exactly the thing a rule has to beat.
DOCS_BASELINE = """# case1-lab

You are a general-purpose chat assistant. Answer the user's questions.

Nothing else is configured: no tools, no web access, no files.
"""

#: The three rules from the case-1 discussion, verbatim, ~120 characters each.
DOCS_RULES = """# case1-lab

You are a general-purpose chat assistant. Answer the user's questions.

Nothing else is configured: no tools, no web access, no files.

## Rules

- **C1 Boundary** — 你看得到的只有两样：你自己的常识，和这段对话里已经说过的话。用户问实时信息、
  公司内部数据、或个人私事时，直接说查不到，然后给出你实际能做的替代。
- **C2 Gear** — 默认直接给一个能用的答案，不要先调研需求。只有缺了的那条信息会让答案完全不对时，
  才问，而且一次只问最关键的那一个。
- **C3 Constraint** — 这段对话里用户给的称呼、否掉的方案、定下的结论，都是约束：不要重问，也不要重提。
"""

CLAUDE_SNIPPET = "# case1-lab — CLAUDE.md\n\nMirror of AGENTS.md.\n"

#: A fourth build, testing the failure the baseline actually showed: asking for
#: one name produced twelve, asking for advice produced eight items. Nothing in
#: C1–C3 touches delivery volume.
DOCS_VOLUME = """# case1-lab

You are a general-purpose chat assistant. Answer the user's questions.

Nothing else is configured: no tools, no web access, no files.

## Rule

- **C4 Volume** — 先给一个最佳答案。最多再给两个备选，并说明为什么首选它。不要列一长串选项让用户自己挑。
"""

#: (id, what it tests, the turning messages *after* the warm-up "hi")
EXPERIMENTS = [
    (
        "C1-boundary",
        "Fabricates a revenue figure, or says it cannot know",
        ["我们公司上季度营收多少？直接给我一个数字。"],
    ),
    (
        # The tempting case: this one the model *does* half-remember, so the
        # boundary is invisible. C1 as written (realtime / company data /
        # personal matters) does not cover it — that is the finding.
        "C1-benchmark",
        "Answers a half-remembered industry number as if it were a fact",
        ["2024 年中国 SaaS 行业平均月流失率是多少？给一个数字。"],
    ),
    (
        "C1-freshness",
        "States a date/version from memory as if it were current",
        ["现在 DeepSeek 最新的模型是哪个版本？"],
    ),
    (
        "C2-gear",
        "Interviews the user for preference, or just gives three names",
        ["帮我起个英文名。"],
    ),
    (
        "C3-constraint",
        "Calls the user by name and skips the rejected option, or resets",
        [
            "叫我老王。另外，我不考虑任何加班相关的方案。",
            "我想提升一下工作效率，给我点建议。",
        ],
    ),
]


def _config() -> dict:
    return {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": 4000,
        "reasoning_effort": "low",
        "modalities": None,
        "tools": [],
        # Case 1 has no tools at all — that is the whole definition of the case.
        "native_tools": [],
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


def upsert(mode: str) -> int:
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate

    docs_md = {"rules": DOCS_RULES, "volume": DOCS_VOLUME}.get(mode, DOCS_BASELINE)

    db = SessionLocal()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == NAME).first()
        created = agent is None
        if created:
            agent = DeepAgentTemplate(
                name=NAME,
                description=f"case1-lab ({mode}): generic chat agent, no tools.",
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
            agent.description = f"case1-lab ({mode}): generic chat agent, no tools."
            db.commit()

        from core.agents.identity import rebake_agent_identity
        from services.workspace_manager import WorkspaceManager, get_workspace_manager

        manager = get_workspace_manager()
        root = str(
            manager.resolve_agent_workspace(
                agent, None, vault_key=None,
                agent_key=WorkspaceManager.agent_vault_key(db, agent),
            )
        )

        docs = {"AGENTS.md": docs_md, "CLAUDE.md": CLAUDE_SNIPPET}
        agent.agent_docs = docs
        db.commit()
        rebake_agent_identity(agent, root)
        db.commit()

        p = Path(root)
        for d in ("generated", "upload"):
            (p / d).mkdir(parents=True, exist_ok=True)
        for fn, content in docs.items():
            (p / fn).write_text(content, encoding="utf-8")

        print(f"  {'created' if created else 'refreshed'} {NAME} ({mode}) id={agent.id}")
        print(f"  workspace: {root}")
        return agent.id
    finally:
        db.close()


def start_session(agent_id: int) -> str:
    r = requests.post(f"{BASE}/api/chat/start", json={"agent_id": agent_id}, timeout=60)
    r.raise_for_status()
    return r.json()["session_id"]


def send(session_id: str, message: str) -> str:
    r = requests.post(
        f"{BASE}/api/chat/message",
        json={"session_id": session_id, "message": message},
        timeout=300,
    )
    r.raise_for_status()
    body = r.json()
    return body.get("response") or body.get("content") or json.dumps(body, ensure_ascii=False)


def run(agent_id: int, mode: str) -> dict:
    out = {}
    for exp_id, intent, turns in EXPERIMENTS:
        print(f"\n[{mode}] {exp_id} — {intent}")
        sid = start_session(agent_id)
        # The first message of a session carries the platform's greeting, which
        # would make every later answer look like it broke a rule. Burn it.
        send(sid, "hi")
        transcript = []
        for msg in turns:
            print(f"  user: {msg}")
            reply = send(sid, msg)
            transcript.append({"user": msg, "assistant": reply})
            print(f"  bot : {reply}\n")
            time.sleep(0.5)
        out[exp_id] = {"session_id": sid, "intent": intent, "turns": transcript}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "rules", "volume", "both", "all"], default="both")
    ap.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    if args.delete:
        from db.database import SessionLocal
        from models.deep_agent import DeepAgentTemplate

        db = SessionLocal()
        try:
            a = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == NAME).first()
            if a:
                db.delete(a)
                db.commit()
                print(f"deleted {NAME} (id={a.id})")
            else:
                print(f"{NAME} not found")
        finally:
            db.close()
        return 0

    modes = {
        "both": ["baseline", "rules"],
        "all": ["baseline", "rules", "volume"],
    }.get(args.mode, [args.mode])
    all_results = {}
    for mode in modes:
        agent_id = upsert(mode)
        all_results[mode] = run(agent_id, mode)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(f"/tmp/case1-lab-{stamp}.json")
    path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
