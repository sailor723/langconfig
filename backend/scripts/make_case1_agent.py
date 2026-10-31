#!/usr/bin/env python
"""Create/refresh `case-1-doc-chat` — the document-chat case, as an agent.

Notebook equivalents: module-4 `4.0_document_chatbot` (long-context) and the
LangChain tutorial's minimal RAG on top of the semantic-search engine
(https://docs.langchain.com/oss/python/langchain/knowledge-base).

The agent has exactly ONE tool: `rag_search`. That is the whole design:

  * no `web_search` — this case is about a closed corpus; giving it the web would
    let it answer the unanswerable questions from outside the document, which is
    precisely the failure the case measures;
  * no file tools — reading the PDF directly is the KV approach, and the comparison
    between the two is the lesson. This agent must go through retrieval, or the
    citations it produces would be decorative.

Usage:
    .venv/bin/python scripts/make_case1_agent.py          # create or refresh
    .venv/bin/python scripts/make_case1_agent.py --delete
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

NAME = "case-1-doc-chat"
TOOLS = ["rag_search"]

SYSTEM_PROMPT = """你是一个文档问答助手。用户会就他们上传的文档向你提问。"""

AGENTS_MD = """# 文档问答

你只回答一个问题：**用户上传的那份文档里写了什么**。

## 规则

- **先查再答。** 每次回答前先调用 `rag_search`，不要凭记忆回答文档内容。
- **答案只能来自检索到的段落。** 每个结论后面标注来源，用 `[1]` `[2]` 指向段落编号，
  并写出文件名和页码（检索结果里都有）。
- **分清三种"没有"**：
  1. 文档里没写这件事 → 说"文档里没有提到"，并写出你用的查询词；
  2. 你检索了但没命中（查询词没找准）→ 换个说法再查一次，最多两次；
  3. 文档确实缺失/没索引 → 说明"这个账户还没有可检索的文档"。
  这三种不能混成一句"我不知道"。
- **文档以外的知识**：只有用户明确要求时才用，并且必须显式标注
  "以下是文档之外的信息"。
- 不要引用不存在的段落编号。
"""


def _config() -> dict:
    return {
        # Left unset → the account's default model (Settings → Models).
        "model": None,
        "temperature": 0.0,
        "max_tokens": 4000,
        "reasoning_effort": "low",
        "modalities": None,
        "tools": [],
        "native_tools": list(TOOLS),
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


def upsert() -> int:
    from core.agents.identity import rebake_agent_identity
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate
    from services.workspace_manager import WorkspaceManager, get_workspace_manager

    db = SessionLocal()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == NAME).first()
        created = agent is None
        cfg = _config()
        if created:
            agent = DeepAgentTemplate(
                name=NAME,
                description="case 1 · 文档问答：只有一个 rag_search 工具，答案必须来自检索到的段落",
                category="Custom",
                config=cfg,
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
            merged = dict(agent.config or {})
            merged.update(cfg)
            agent.config = merged
            db.commit()

        manager = get_workspace_manager()
        root = str(
            manager.resolve_agent_workspace(
                agent, None, vault_key=None,
                agent_key=WorkspaceManager.agent_vault_key(db, agent),
            )
        )
        docs = {
            "AGENTS.md": AGENTS_MD,
            "CLAUDE.md": f"# {NAME} — CLAUDE.md\n\nMirror of AGENTS.md.\n",
        }
        agent.agent_docs = docs
        db.commit()
        rebake_agent_identity(agent, root)
        db.commit()

        p = Path(root)
        for d in ("generated", "upload"):
            (p / d).mkdir(parents=True, exist_ok=True)
        for fn, content in docs.items():
            (p / fn).write_text(content, encoding="utf-8")

        print(f"{'created' if created else 'refreshed'} {NAME} (id={agent.id}) tools={TOOLS}")
        return agent.id
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
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
        finally:
            db.close()
        return 0
    upsert()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
