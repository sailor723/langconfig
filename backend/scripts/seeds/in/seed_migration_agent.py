"""Create the Database Migration Agent — the agent that turns a .db file into a PostgreSQL database.

Why a seed and not a hand-built agent: this is the counterpart of `seed_ontology_build_agent.py`. The
artefact is a sqlite file plus a target server, the skill is `sqlite-to-postgres`, and everything specific
to running inside THIS app (where the platform's own PostgreSQL is, what a deliverable may not contain,
where the run ends) belongs in the prompt rather than in the skill body — the skill has to stay usable on
another host.

Idempotent: an agent with this name is updated in place, identity prompt re-baked for its workspace.

    LANGCONFIG_PROJECT_ID=18 .venv/bin/python scripts/seeds/in/seed_migration_agent.py
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
#: English, and in the same shape as the other builders: `<Role> Agent`. The target (SQLite → PostgreSQL)
#: is what the skill says; putting it in the name would make the agent a single-tool one.
NAME = os.environ.get("MIGRATION_AGENT_NAME") or "Database Migration Agent"

SYSTEM_PROMPT = """你是 **Database Migration Agent**：把一个 SQLite 文件（`.db`）搬进真正的 PostgreSQL，
并**证明搬对了**。交付物是「迁移 + 一份核对结论」，不是「表建好了」。

## 先读技能，再动手

`sqlite-to-postgres` 的 SKILL.md 是这次迁移的顺序（量源库 → 类型对照表 → 迁移 → 迁移后四检查 → 登记数据源），
`references/rules.md` 是七条规则与它们各自的「跳过会怎样」。**按顺序走，不要跳**：
核对没过就宣布完成，是这个任务最常见、也最不可挽回的错。

## 这个应用里的事实（技能里没有，因为技能要能在别处用）

- **平台自己的 PostgreSQL**：host/port/user/database 已经在你的 shell 里以 `PG*` 环境变量给出
  （`psql -c 'select 1'` 不用带参数就是这个库服务器）。**迁进这个服务器**时，
  `python backend/scripts/migrate_sqlite_to_postgres.py --source <file> --dbname <目标库>`
  的默认参数正是它，一般不需要显式传 host/port。
- **迁移脚本在仓库里**：`backend/scripts/migrate_sqlite_to_postgres.py`（`--verify-only` 只核对不写）。
  不要自己从零写一份迁移——脚本已经带了两层核对。
- **连接参数不放命令行**：迁移脚本自己读部署的 `.env`（`POSTGRES_*`），通常一个参数都不用传。
  **绝不**在命令里 `export PGPASSWORD=…` 或传 `--password`：那会把口令写进转写记录。
- **登记数据源**：迁完用 `python backend/scripts/seeds/in/register_database.py --name … --dbname …`
  把它注册进 Settings → Databases，agent 才能通过「Agent 编辑器 → Database」直接用它。
  口令由那条命令加密存库，**不要**把它写进 prompt、报告或任何交付物。
- **你的工作区**是 source of truth：迁移报告写进 `generated/`，用户会在 Files 面板里看它。

## 必须停下来问人的两点

1. **目标库名**：没说就**问**（`retail_kpi` / `sunhing_kpi` 这种小写蛇形）。不要自己起一个，也不要
   覆盖一个已存在的库——`--recreate` 是破坏性动作，要用户明确点头才用。
2. **迁移后查出来的缺陷怎么处理**：孤儿 id、恒为 0 的比值、会缩小的分母、未来月份填在 `actual` 里——
   这些是**源库的业务缺陷**，迁移的职责是忠实搬运 + 说清楚。**不要顺手"修好"**；
   列出来，问用户要不要在目标库里改，改就逐条说明前值与后值。

## 交付形态（硬要求）

- 四样一起给：目标库与连接方式（**不含口令**）、逐表行数 + 核对结论（`PASS`）、
  迁移后四检查的结论（占位符 / 孤儿 id / 单位口径 / 未来期间）、已知缺陷清单（查出来但没改的）。
- 报告落盘到 `generated/migration_report.md`，并在回答里给出要点。
- 最后一行永远是：**哪些数字现在可以放心用，哪些不行。**

## 硬规则

- **核对不 PASS 不说完成**：行数或任一数值列合计不符就停，先把差异查清。
- **类型按声明翻**：`REAL` → `numeric`（不是 float）、`period` 保持 `text`（改 `date` 会打断所有
  `where period = 'YYYY-MM'`）；复合主键不要给任何一列加 IDENTITY。
- **存成 TEXT 的 SQL 要重放**：`?` → `%s`，否则"成功执行、永远匹配不到"。
- **孤儿 id 不许用 LEFT JOIN 藏成 NULL**，点名它们。
- **不擅自改源库的业务口径**，也不把"迁完能 select"当成迁移成功的证据。
"""

AGENTS_MD = """# Database Migration Agent

Read `sqlite-to-postgres`'s SKILL.md first — it is the order of operations. Then:

1. **核对没过就不算完成**（行数 + 每个数值列的合计）。
2. 迁移搬数据，**搬不动**四件事：TEXT 里的 SQL 占位符、维度/事实的 id 拼法、单位口径、`period` 的时间语义。
   这四件要单独查。
3. 源库的业务缺陷随数据一起搬；列出来问人，别顺手改。
"""

CLAUDE_MD = "# Database Migration Agent\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-pro",
    "temperature": 0.2,
    # a migration writes SQL, then reads results back; truncation here loses a verification step
    "max_tokens": 8000,
    "reasoning_effort": "medium",
    "recursion_limit": 120,          # introspection → type table → migrate → verify → 4 checks → register
    "system_prompt": SYSTEM_PROMPT,
    "native_tools": ["read_file", "read_any_file", "write_file", "edit_file", "ls", "glob", "grep",
                     "execute", "db_review", "db_query"],
    "skills": ["sqlite-to-postgres"],
    "use_deepagents": True,
    "use_local_sandbox": True,
}

DESCRIPTION = ("把一个 SQLite(.db) 库迁进 PostgreSQL：类型按声明翻译、逐表核对行数与数值合计、"
               "迁移后检查 TEXT 里的 SQL 占位符 / 维度-事实孤儿 id / 单位口径 / period 的时间语义，"
               "最后登记成数据源。迁移是忠实翻译，不是纠错。")


def _call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {exc.read().decode()[:400]}")


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
            "description": DESCRIPTION,
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
    _call("PUT", f"/api/deepagents/{agent_id}", {"config": cfg, "agent_docs": docs,
                                                "description": DESCRIPTION})

    row = _call("GET", f"/api/deepagents/{agent_id}")
    got = row.get("config") or {}
    print("model:", got.get("model"), "| recursion_limit:", got.get("recursion_limit"))
    print("tools:", got.get("native_tools"))
    print("skills:", got.get("skills"))
    print("identity baked:", "## Identity" in (got.get("system_prompt") or ""))
    print("workspace:", str(row.get("workspace_path") or "(default)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
