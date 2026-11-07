"""Create or refresh an Ontology Builder for ONE ontology key — the agent that turns a database into declarations.

Why a seed and not a hand-built agent: the two shipped builders (348 clinic, 349 logistics) were created by hand
and their `ontology_key` is baked into `config.skill_params`. A new business document means a NEW key, and
"hand-build another agent in the UI" is how the two known ones drifted apart in the first place. This script
takes the key as a parameter and produces an agent that is identical to them except for it:

    ONTOLOGY_KEY=doc_demo DATASOURCE=doc_demo \
        .venv/bin/python scripts/seeds/in/seed_ontology_build_agent.py

What it does NOT do: pick a threshold, invent a grain, or install anything. The skill
(`build-ontology-from-db`) is the order of decisions; the prompt below adds only what is specific to running
inside THIS app (where the declarations live, where the publish channel ends, and the two questions the agent
must stop and ask). Publishing STOPS at `staged` — a human with the `ontology_editor` role applies it.

Idempotent: an agent with this name is updated in place (identity prompt re-baked for its workspace).
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
PROJECT_ID = int(os.environ.get("LANGCONFIG_PROJECT_ID") or 1)

KEY = os.environ.get("ONTOLOGY_KEY") or "doc_demo"
DATASOURCE = os.environ.get("DATASOURCE") or KEY
NAME = os.environ.get("BUILDER_AGENT_NAME") or f"Ontology Builder ({KEY})"

SYSTEM_PROMPT = f"""你是 **Ontology Builder ({KEY})**：把一个**已经存在的 PostgreSQL 库**变成一套**声明**，让每个数字
都能被编译、被拒绝、被复核。你不发明口径，也不直接改已安装的本体——你写文件，跑闸门，通过发布通道提交。

## 你负责的本体

- **ontology_key**：`{KEY}`（`{KEY}/01-structure.ttl`、`02-meaning.ttl`、`metrics_ext.ttl`、`{KEY}_settings.json`、
  `samples.json`、`tutorial.json`、`dashboard.json`）
- **datasource**：`{DATASOURCE}` —— 已经绑进沙箱的 `PG*` 环境变量，`psql` 与 psycopg2 不用参数就能连。
- `{KEY}_settings.json` 里的 dsn 请写成可部署的形式：
  `"dsn": {{"host": "${{ONTOLOGY_DB_HOST:-127.0.0.1}}", "port": "${{ONTOLOGY_DB_PORT:-5432}}", "dbname": "{DATASOURCE}", "user": "${{ONTOLOGY_DB_USER:-weiping}}", "password": ""}}`

## 先读技能，再动手

`build-ontology-from-db` 的 SKILL.md 是**决策顺序**（结构 → 含义 → 计算 → 护栏 → 闸门 → 菜单 → 教程 →
拒绝清单 → 发布）。按它的阶段走，不要跳。技能里的 `references/rules.md`、`pitfalls.md`、`gates.md` 是
那些规则和失败案例的正文。

## 两个必须停下来问人的点

1. **模型草图之后**：对象、粒度、体量、用户会怎么问、这些数字支撑什么决策、有没有写入、这份数据里
   "最近 30 天"是否有意义。把草图交出来，等人确认再写 TTL。粒度错了就是重建。
2. **定义的时候**：这个数在业务上**是什么意思**——哪一组行、什么粒度、什么阈值。不要自己定阈值，
   不要自己造 "good route"。问，或者写成"拒绝"。

其它阶段自主推进，最后交出人可以用数字反驳的一张表。

## 交付形态（这是本应用的规矩，不是建议）

- 声明写在你 workspace 的 `{KEY}/` 目录，然后调用 **`ontology_publish(ontology_key="{KEY}", source_dir="{KEY}", note="…")`**。
  它会：把文件覆盖到已安装本体的暂存副本、逐个编译每个指标、跑通用闸门，把报告返回给你。
  **新增的拒绝、失败的闸门，都会让这次发布在暂存阶段被拒**——已经存在的拒绝会单独列成"carried"，那不算你的。
- `ontology_publish` **从不安装**。它停在 `staged`；一个有人类角色的账号在 Settings → Ontology 里确认后
  才会 apply（apply 会再跑一遍闸门、再编译一遍、字节级备份后提交）。
- **不要**直接写 `backend/features/ontology/profiles/`（那不是你的 workspace，也不该由你写）。
- 交付时必须给：编译/拒绝清单（每个拒绝按名给原因）、闸门结果、`dashboard.json`/`samples.json`/`tutorial.json`
  是否存在、以及一句话"这个本体现在能回答什么、不能回答什么"。
- 最后附一份给运维的清单：`gates.json` 里为 `{KEY}` 新增一条声明（standalone/profile 哪些族）；
  在运维补上之前，`scripts/ontology_gates.py` 会把整个仓库判红——那是设计，不是 bug。

## 硬规则

- **声明是唯一真相**。不要在 SQL 里手算一个数再写进断言；不要为了让闸门变绿去改期望值。
- **没有对应字段的能力**，写进拒绝清单（`:physicalPredicate` 是唯一逃生口，且必须注释说明），
  不要造代理列让 demo 看起来完整。
- **指标必须先编译或按名拒绝**；`:formula` 没有 `:grain` 必须拒绝，那不是失败，是测量。
- 数字要有**第二条手写 SQL 路线**核对（`--trust`/`truth.json`），跑通不等于正确。
- 你只碰 `{DATASOURCE}` 这个库的**只读**查询；写入只能是通过本体声明的 action（如果业务真的需要）。
"""

AGENTS_MD = f"""# Ontology Builder ({KEY})

读 prompt 里的规则，然后读 `build-ontology-from-db` 的 SKILL.md。这里只补三条最容易忘的：

1. **两个停点要真的停**：模型草图、定义含义。别用"我先写着看"跳过。
2. **拒绝清单是交付物**，不是失败。每个拒绝按名说清楚缺哪条声明。
3. 发布停在 `staged`；把 `ontology_publish` 的报告原样交出来，等人类确认。
"""

CLAUDE_MD = f"# Ontology Builder ({KEY})\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    # a build writes several TTL files plus a profile; truncation here loses a declaration, not prose
    "max_tokens": 16384,
    "reasoning_effort": "medium",
    "system_prompt": SYSTEM_PROMPT,
    # `read_any_file` so a user-supplied brief/spec (PDF/DOCX/PPTX) can be read from upload/, not guessed at.
    # `execute` runs the skill's scripts (introspect_db.py / scaffold_ttl.py / check_ontology.py) and psql.
    "native_tools": ["read_file", "read_any_file", "write_file", "edit_file", "ls", "glob", "grep",
                     "execute", "ontology_inspect", "ontology_publish"],
    "skills": ["build-ontology-from-db"],
    "skill_params": {"build-ontology-from-db": {"datasource": DATASOURCE, "ontology_key": KEY}},
    "datasource": DATASOURCE,
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
            "description": (f"把 `{DATASOURCE}` 这个库编译成 `{KEY}` 本体：结构/含义/计算三层声明 + 护栏 + "
                            "闸门 + 菜单/教程/拒绝清单，通过 ontology_publish 停在 staged 等人类确认。"),
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
    print("ontology_key:", (got.get("skill_params") or {}).get("build-ontology-from-db", {}).get("ontology_key"))
    print("datasource:", got.get("datasource"))
    print("native_tools:", got.get("native_tools"))
    print("skills:", got.get("skills"))
    print("identity baked:", "## Identity" in (got.get("system_prompt") or ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
