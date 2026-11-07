"""Seed (or refresh) the `logics_query` DeepAgent — the agent that ANSWERS questions, it does not build.

The family, and what each one is for:

    Ontology Builder (348 / 349)   takes a database and produces declarations       → publishes
    Ontology Editor  (350)         changes what a number MEANS                       → stages a publish
    logics_query     (this one)    answers a business question from those numbers    → reports, never writes

A query agent that can also publish is a query agent whose answers you cannot trust: the whole point is
that the number came from declarations nobody touched at answer time. So this agent gets `ontology_ask`
and read-only tools, and no publish tool at all.

Its parameters live on the skill (`answer-ontology-question` declares `ontology_key` and `workbench`), and
`core/skills/params.py` renders them into the prompt and writes `/skills/…/params.json` — the same
mechanism the editors use, so "which ontology does this agent answer for" is configuration, not prose.

Creation goes through the same API the UI uses (identity baking, workspace resolution, AGENTS.md), and a
refresh re-bakes the identity block, because a PUT replaces `system_prompt` verbatim.

    cd backend && .venv/bin/python scripts/seeds/in/seed_logics_query_agent.py
    LANGCONFIG_BASE=http://127.0.0.1:8765 .venv/bin/python scripts/seeds/in/seed_logics_query_agent.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

BASE = os.environ.get("LANGCONFIG_BASE", "http://127.0.0.1:8765").rstrip("/")
NAME = "logics_query"
PROJECT_ID = int(os.environ.get("LANGCONFIG_PROJECT_ID") or 1)

SYSTEM_PROMPT = """你是 logics_query：一个**answering** agent。用户问一个业务问题，你通过本体给出那个数字——或者给出"本体答不了"的按名拒绝。你不建模，不改本体，不发布。

Answer in Chinese unless the user writes in another language. Never invent a number, and never write SQL.

## 你的唯一工具是 ontology_ask

把它当唯一的取数入口：

    ontology_ask(question="用户的原话", ontology_key="logistics", confirm=false)

它会跑这个本体自己的 Query 流水线（也就是它 Query 页面背后的那条）：先把问题匹配到已声明的指标/类/动作（规则优先，只在不确定时才问模型），再由本体的编译器生成 SQL，护栏限制它，最后把数字写成人话。

三种返回，三种都算"答了"：
- **数字**（含分组行）+ 它来自的定义 + 编译出的 SQL + 护栏备注 → 原话引用，别改写数字；
- **REFUSED**：它按名说了缺哪条声明（或哪条定义是业务没定的）→ 这就是答案，如实转述，不要说"可能/大约/应该是"；
- **NEEDS CONFIRMATION**：问题里带了时间范围或客户，它把理解回显给你 → 先把理解给用户看，同意后再用 confirm=true 跑一次。

## 规矩

0. **不要探索工作区。** 回答一个问题只需要 `ontology_ask`（必要时加一次 `ontology_inspect`）；
   不要为了"先看看"去 `ls`/`find`——那是浪费一次工具调用，也不会改变答案。
1. **一个数字只能来自 ontology_ask。** 你自己算、自己写 SQL、自己"估一下"，都是禁止的。
2. **问题原话照搬。** 不要先"整理"用户的问题——匹配靠的就是那些词。
3. **拒绝不是失败。** 拒绝说明本体缺一条声明，这是最有用的输出：说清缺什么，以及用户该怎么问才答得出（换成已声明的说法）。
4. **口径必须一起说。** 回答里带上：这个数是什么（定义）、算的是哪些行、分维度没有、时间窗有没有、护栏做了什么（分页/计划预算）。
5. **跨本体**：用户没指定本体时用参数里的默认（下面的 Skill parameters）；要问另一个本体就在 question 之外指定 ontology_key。
6. **NOT RUN 就写 NOT RUN**：如果 ontology_ask 报错（流水线跑不起来、本体不存在、数据库连不上），如实说哪一步没跑，不要用别的途径凑一个数。

## 别的工具

- `ontology_inspect(ontology_key=..., metric=...)`：看某个指标的声明、编译 SQL、值、护栏备注；`question=...` 看它怎么解析（诊断"为什么被拒"时用）。
- `read_file` / `ls` / `glob` / `grep` / `execute`：只读排查用。`execute` 只允许跑只读命令（psql 的 SELECT 也不行——取数只能走 ontology_ask）。

## 汇报格式

    Q: 用户原话
    A: 数字（或按名拒绝 / 需要确认的理解）
       口径：哪个指标、哪些行、分不分维度、有没有时间窗
       SQL：（编译出来的那条，可引用）
   未答/未跑：按名列出
"""

AGENTS_MD = """# logics_query

用本体回答业务问题。**只回答，不建模，不发布。**

## 唯一的取数入口

```
ontology_ask(question="用户的原话", ontology_key="logistics", confirm=false)
```

- 返回数字 → 原文引用数字 + 说清口径（哪个指标、哪些行、分维度、时间窗、护栏）
- 返回 REFUSED → 按名转述缺的那条声明，并给出"怎么问才答得出"
- 返回 NEEDS CONFIRMATION → 先把理解给用户看，同意后 confirm=true

## 不做的事

- 不写 SQL、不用自由查询绕开本体（包括 psql）
- 不建模、不改声明、不发布（那是 Ontology Builder / Ontology Editor 的活）
- 不把"估计/大约/应该是"当成答案

## 查不到时

本体答不了，就说**答不了、缺哪条声明**。这比一个编出来的数字有用得多。

## 验证

`ontology_inspect(ontology_key=..., metric=...)` 看指标的声明与编译 SQL；
`ontology_inspect(..., question=...)` 看某句话被解析成什么（诊断拒绝时用）。
"""

CLAUDE_MD = "# logics_query\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    # the answer has to carry the definition, the SQL and the guard notes; 4096 truncated a report before
    "max_tokens": 8192,
    "reasoning_effort": "low",
    "system_prompt": SYSTEM_PROMPT,
    # NO ontology_publish, NO write_file tools: an answering agent that can change the ontology can no
    # longer be trusted to answer from it.
    "native_tools": ["ontology_ask", "ontology_inspect", "read_file", "ls", "glob", "grep", "execute"],
    "skills": ["answer-ontology-question"],
    "skill_params": {"answer-ontology-question": {"ontology_key": "logistics",
                                                  "workbench": "http://127.0.0.1:8098"}},
    "use_deepagents": True,
    "use_local_sandbox": True,
}


def _call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {exc.read().decode()[:500]}")


def _baked_prompt(agent_id: int) -> str:
    """Base prompt + identity + workspace boundary, exactly as the create path writes it."""
    from core.agents.identity import build_identity_system_prompt
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate
    from services.workspace_manager import WorkspaceManager, get_workspace_manager

    db = SessionLocal()
    try:
        agent = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if agent is None:
            raise SystemExit(f"agent {agent_id} disappeared between create and prompt bake")
        ws = str(get_workspace_manager().resolve_agent_workspace(
            agent, PROJECT_ID,
            vault_key=WorkspaceManager.project_vault_key(db, PROJECT_ID) or None,
            agent_key=WorkspaceManager.agent_vault_key(db, agent),
        ))
        return build_identity_system_prompt(SYSTEM_PROMPT, agent_id, ws, {"AGENTS.md": AGENTS_MD})
    finally:
        db.close()


def _find_existing() -> int | None:
    for row in _call("GET", "/api/deepagents/") or []:
        if row.get("name") == NAME:
            return int(row["id"])
    return None


def main() -> int:
    docs = {"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD}
    existing = _find_existing()
    if existing is None:
        created = _call("POST", "/api/deepagents/", {
            "name": NAME,
            "description": ("Answers a business question from an ontology's declared numbers — through "
                            "the ontology's own Query pipeline (rules-first intent, compiled SQL, "
                            "guardrails, verified prose). Refuses by name what the ontology cannot "
                            "answer. Never writes SQL, never changes the ontology."),
            "category": "data",
            "project_id": PROJECT_ID,
            "agent_docs": docs,
            "config": CONFIG,
        })
        agent_id = created.get("id")
        print("created:", agent_id, NAME)
    else:
        agent_id = existing
        print("found:", agent_id, NAME)

    cfg = dict(CONFIG, system_prompt=_baked_prompt(agent_id))
    _call("PUT", f"/api/deepagents/{agent_id}", {"config": cfg, "agent_docs": docs})

    row = _call("GET", f"/api/deepagents/{agent_id}")
    got = row.get("config") or {}
    print("native_tools:", got.get("native_tools"))
    print("skills:", got.get("skills"))
    print("skill_params:", json.dumps(got.get("skill_params"), ensure_ascii=False))
    print("identity baked:", "## Identity" in (got.get("system_prompt") or ""))
    print("publish tool present (must be False):", "ontology_publish" in (got.get("native_tools") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
