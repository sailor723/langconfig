#!/usr/bin/env python3
"""Seed the **DB Manager** agent — a plain (non-deep) agent that manages the PostgreSQL server.

Why a plain agent and not a deep agent: this job is one linear loop — look at what is there, describe it,
ask the database, write one statement — with a small tool set and no filesystem. A deep agent would add a
sandbox, a subagent layer and a `write_todos` notebook to a task that needs none of them; measured cost is
a prompt big enough to bury the rules that matter here (two-phase writes, one statement, refusals).

What it can do, and where each verb comes from:

    db_list_databases   NEW   which databases exist, size, object count, writable or not
    db_describe         NEW   any database's tables (with row estimates), or one table's columns/keys
    db_execute          NEW   ONE write statement (DDL/DML) against a named database, in two phases
    db_query_agent            have  read-only SELECT against any database, batched
    db_review           have  health check (row counts, nulls, PK/FK candidates) and apply PK/FK
    db_rename_column    have  rename a column that lies about its meaning

The database binding is the SERVER (`dbname=postgres`): every tool names its own target database, exactly
like the ontology pipeline's builder, so one agent serves every database on the box. The password is
encrypted at rest and reaches the tools as PGPASSWORD, never as an argument.

    cd backend && .venv/bin/python scripts/seeds/in/seed_db_manager_agent.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/seed_db_manager_agent.py --apply

Idempotent: an existing row with this name is updated in place.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

NAME = "DB Manager（数据库管理）"

SYSTEM_PROMPT = """你是 **DB Manager**：管这台机器上的 PostgreSQL。你的活是「看清楚、查清楚、改对」，不是「猜」。

## 你能做的（按这个顺序用）

1. **`db_list_databases`** —— 服务器上有哪些库（大小、**表数**、能不能写）**一次拿全**。有人问「有哪些库」
   就从这里开始。**不要**再对每个库各发一条 `db_query_agent` 去数表——表数已经在这一份清单里了（实测：19 个库
   逐个查会直接撞步数上限）。
2. **`db_describe(db_name)`** —— 某个库里有哪些表/视图（带行数估算）；**`db_describe(db_name, table)`** ——
   某张表的列（类型/可空/默认值）、索引、约束、精确行数。**写 SQL 之前先 describe**，不要凭名字猜列。
3. **`db_query_agent(db_name, sql=…)` 或 `sqls=[…]`** —— 只读 SELECT，可一次批量发多条（一条连接一次往返）。
   量数就用它，不要一条一条问。
4. **`db_execute(db_name, sql, confirm=…)`** —— 对某个库跑**一条**写语句（DDL/DML）。**两段式**：
   先不带 confirm（或 confirm=false）拿到计划 → 把语句原样给人看 → 人同意了才 `confirm=true`。
5. **`db_review(db_name)`** —— 体检（行数/空值/主键外键候选），`apply=true` 可以把键建上。
6. **`db_rename_column(db_name, table, old, new)`** —— 列名谎报含义时改名，改完记得再 describe 验证。

## 硬规则

- **先看再改**：任何 `db_execute` 之前，至少有 `db_describe` 或 `db_query_agent` 的证据说明你要改的东西长什么样。
- **一份清单一次拿**：跨库的规模/数量用 `db_list_databases` 一次问完；确需逐个库查时，用 `db_query_agent` 的
  `sqls=[…]` 批量发给**同一个**库，不要一库一连接地循环。
- **一次一条语句**：堆叠（`…; DROP …`）会被工具拒；服务器级动作（DROP DATABASE / DROP SCHEMA / ALTER SYSTEM /
  角色与授权）也会被拒，那类事要人在 psql 里做。
- **平台库不写**：`langconfig` 这个库是应用自身的状态，写操作会被告由参数拒绝 —— 那里只读查。
- **两段式不许跳**：没人确认就不 `confirm=true`。你改的是别人的数据。
- **改完要证明**：`db_execute` 之后用 `db_describe`（或 `db_query_agent`）回读一次，把「改之前 → 改之后」的数字或列名贴出来。
  没有回读的「已修改」不算完成。
- **不确定就问**：库名/表名拿不准时，先 `db_list_databases` / `db_describe`，不要猜一个相近的名字。

## 汇报

- 每次只报三样：**做了什么**（哪条语句、哪个库）、**证明了什么**（回读到的数字/列名）、**没做什么**（被拒绝或需要人定的）。
- 被工具拒绝时，把拒绝原文贴出来，不要换个写法绕过去。
"""

AGENTS_MD = """# DB Manager

读 prompt 里的规则。这里只补四条最容易忘的：

1. **先 `db_list_databases` → 再 `db_describe` → 再写 SQL**。凭名字猜列的语句会被回滚，还要多花一轮。
2. **`db_execute` 是两段式**：先拿计划给人看，人同意了才 `confirm=true`；一次只跑一条语句。
3. **平台库（`langconfig`）只读**：写操作会被按参数拒绝。
4. **改完回读**：`db_describe` / `db_query_agent` 把改前改后的样子贴出来，否则不算完成。
"""

CLAUDE_MD = "# DB Manager\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 8192,
    "reasoning_effort": "medium",
    "recursion_limit": 80,
    "system_prompt": SYSTEM_PROMPT,
    "native_tools": ["db_list_databases", "db_describe", "db_query_agent", "db_execute", "db_review",
                     "db_rename_column"],
    "skills": [],
    "use_deepagents": False,
}


def _env(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    env = REPO / ".env"
    if env.is_file():
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return default


def database_block(dbname: str) -> dict:
    """The server as this agent's database; every tool names its own target database."""
    user = _env("ONTOLOGY_DB_USER") or _env("POSTGRES_USER")
    password = _env("ONTOLOGY_DB_PASSWORD") or _env("POSTGRES_PASSWORD")
    block = {"mode": "custom", "host": _env("ONTOLOGY_DB_HOST", "127.0.0.1"),
             "port": int(_env("ONTOLOGY_DB_PORT") or _env("POSTGRES_PORT") or 5432),
             "dbname": dbname, "user": user, "password": password}
    from services.agent_database import encrypt_config_secrets  # noqa: PLC0415

    return encrypt_config_secrets({"database": block})["database"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=NAME)
    ap.add_argument("--dbname", default="postgres", help="the database bound to the agent (server default)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    config = {**CONFIG, "database": database_block(args.dbname)}
    print(f"agent: {args.name!r}  deep={config['use_deepagents']}  model={config['model']}")
    print(f"tools: {config['native_tools']}")
    print(f"database: {config['database']['host']}:{config['database']['port']}/{args.dbname} "
          f"user={config['database'].get('user')} "
          f"password={'set (encrypted)' if config['database'].get('password') else 'NOT SET'}")

    from db.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        row = db.execute(text("select id, is_public from deep_agent_templates where name = :n"),
                         {"n": args.name}).fetchone()
        payload = json.dumps(config, ensure_ascii=False)
        if row:
            print(f"existing row id={row[0]} — would UPDATE in place")
            if not args.apply:
                print("dry run — re-run with --apply")
                return 0
            db.execute(text("update deep_agent_templates set config = cast(:c as jsonb), "
                            "agent_docs = cast(:d as json), is_public = true where id = :i"),
                       {"c": payload, "i": row[0],
                        "d": json.dumps({"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD},
                                        ensure_ascii=False)})
            db.commit()
            print(f"updated agent {row[0]} {args.name!r}")
            return 0
        print("no such row — would INSERT")
        if not args.apply:
            print("dry run — re-run with --apply")
            return 0
        db.execute(text("""insert into deep_agent_templates
                             (name, description, category, config, middleware_config, subagents_config,
                              backend_config, guardrails_config, agent_docs, usage_count, version,
                              is_public, is_community, created_at, updated_at)
                           values (:n, :d, 'data', cast(:c as jsonb), '[]', '[]',
                                   '{"type": "state", "config": {}, "mappings": null}',
                                   '{"interrupts": {}}', cast(:docs as json), 0, '1.0.0',
                                   true, false, now(), now())"""),
                   {"n": args.name,
                    "d": ("管这台 PostgreSQL：列出所有库、描述任意库/表、批量只读查询、两段式写一条 DDL/DML、"
                          "体检建键、改名。先看再改，改完回读。"),
                    "c": payload,
                    "docs": json.dumps({"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD},
                                       ensure_ascii=False)})
        db.commit()
        new_id = db.execute(text("select id from deep_agent_templates where name = :n"),
                            {"n": args.name}).scalar()
        print(f"created agent {new_id} {args.name!r}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
