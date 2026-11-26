#!/usr/bin/env python3
"""Seed `test_db` — the smallest possible database agent: ONE LangGraph SQL tool, nothing else.

Purpose: a probe you can configure and poke without a pipeline in the way. It exists to answer "does an
agent plus a Database setting actually reach the databases on this box?" — so it has:

* **one tool.** `db_query_langgraph` — the hand-built LangGraph SQL agent (list tables → read schema →
  generate query → check query → run read-only → explain). The agent asks in natural language; it never
  writes SQL itself, and there is no DDL, no write path, no filesystem and no subagents. If something fails
  here it is the graph, the model, or the connection — not the design.
* **no deep agent.** `use_deepagents: false`: a plain `create_agent` loop that holds the one tool. Faster
  to build, nothing to assemble, and no sandbox to misconfigure.
* **a Database setting.** `config.database` is a custom block (host/port/user + encrypted password,
  `dbname=chinook` — the sample business database, so a question asked without a database name lands on
  real tables instead of on `postgres`, which has none). That is where the credential comes from — `db_query_langgraph` takes a database NAME (or
  none, meaning "the database this connection points at"), never a password; the connection details reach
  the graph as the per-call override, taken from the same run-scoped binding `db_query` uses. Configure it in the agent editor
  (Agent → Database) or point it at a Settings → Databases catalogue entry; with no Database setting,
  `db_query` has no server to connect to and every call fails with "no password supplied".

    cd backend && .venv/bin/python scripts/seeds/in/seed_test_db_agent.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/seed_test_db_agent.py --apply

Idempotent: an existing row named `test_db` is updated in place.
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

NAME = "test_db"

SYSTEM_PROMPT = """你是 **test_db**：一个用来试数据库连接的最小 agent。你只有一个工具 `db_query_langgraph`。

## 它是什么

`db_query_langgraph` 不是"执行 SQL"，而是**一条 LangGraph 流水线**：列库里的表 → 读相关表的 schema →
生成 SQL → **自检**这条 SQL → 只读执行 → 用自然语言解释结果。你只负责提问，不写 SQL。

## 怎么用

- **`db_query_langgraph(question="<自然语言问题>")`** —— 问"当前连接指向的那个库"。
- **`db_query_langgraph(question="…", database="<库名>")`** —— 指到同一台服务器上的另一个库。
- 问题要**具体且可判定**：说清指标、口径、筛选条件（例如"customers 表里有多少行"），
  不要问"帮我看看这个库"这种开放问题——那会让流水线自己猜表。

## 连接从哪来

你的连接来自 **Agent → Database** 这一项设置（host / port / user / 加密口令）：流水线拿它当本次调用的连接；
`database` 只指定哪个库。没配 Database 时，工具会退回平台自己的连接——那是配置问题，不是问题本身。

## 汇报

- 给**结论 + 依据**：数字、用到的表、以及流水线报告的 SQL（如果有）。
- 失败就把工具返回的原文贴出来（它通常会说是哪个库/哪张表/哪一列，或者模型/连接出了问题）。
- 不要自己写 SQL 去"绕开"工具：本 agent 只有这一个工具，绕不过去。只读，不能改数据。
"""

AGENTS_MD = """# test_db

只有一个工具：`db_query_langgraph`（LangGraph：列表 → 读 schema → 生成 SQL → 自检 → 只读执行 → 解释）。

1. 用自然语言提问，不要自己写 SQL——写 SQL 是这个工具内部的事。
2. 不传 `database` 就是"当前连接指向的库"；传了就是同一台服务器上的另一个库。
3. 连接来自 **Agent → Database** 设置；没配就是配置错误，不是问题本身。
4. 给结论 + 依据；失败贴原文。本 agent 只读，不能改数据。
"""

CLAUDE_MD = "# test_db\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 4096,
    "reasoning_effort": "medium",
    "recursion_limit": 60,
    "system_prompt": SYSTEM_PROMPT,
    "native_tools": ["db_query_langgraph"],
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
    """The server this agent points at — the same shape the agent editor writes."""
    block = {"mode": "custom",
             "host": _env("ONTOLOGY_DB_HOST", "127.0.0.1"),
             "port": int(_env("ONTOLOGY_DB_PORT") or _env("POSTGRES_PORT") or 5432),
             "dbname": dbname,
             "user": _env("ONTOLOGY_DB_USER") or _env("POSTGRES_USER"),
             "password": _env("ONTOLOGY_DB_PASSWORD") or _env("POSTGRES_PASSWORD")}
    from services.agent_database import encrypt_config_secrets  # noqa: PLC0415

    return encrypt_config_secrets({"database": block})["database"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=NAME)
    ap.add_argument("--dbname", default="chinook",
                    help="the database bound to the agent (default postgres; db_query names its own per call)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    config = {**CONFIG, "database": database_block(args.dbname)}
    print(f"agent: {args.name!r}  deep={config['use_deepagents']}  tools={config['native_tools']}")
    print(f"database setting: {config['database']['host']}:{config['database']['port']}"
          f"/{args.dbname} user={config['database'].get('user')} "
          f"password={'set (encrypted)' if config['database'].get('password') else 'NOT SET'}")

    from db.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        payload = json.dumps(config, ensure_ascii=False)
        docs = json.dumps({"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD}, ensure_ascii=False)
        row = db.execute(text("select id from deep_agent_templates where name = :n"),
                         {"n": args.name}).fetchone()
        if row:
            print(f"existing row id={row[0]} — would UPDATE")
            if args.apply:
                db.execute(text("update deep_agent_templates set config = cast(:c as jsonb), "
                                "agent_docs = cast(:d as json), is_public = true where id = :i"),
                           {"c": payload, "d": docs, "i": row[0]})
                db.commit()
                print(f"updated agent {row[0]} {args.name!r}")
            else:
                print("dry run — re-run with --apply")
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
                                   '{"interrupts": {}}', cast(:docs as json),
                                   0, '1.0.0', true, false, now(), now())"""),
                   {"n": args.name,
                    "d": ("最小数据库 agent：只有 db_query（只读、任意库、可批量）。连接来自 Agent → Database "
                          "设置；用来验证「agent + Database 设置」能不能真的问到库。"),
                    "c": payload, "docs": docs})
        db.commit()
        new_id = db.execute(text("select id from deep_agent_templates where name = :n"),
                            {"n": args.name}).scalar()
        print(f"created agent {new_id} {args.name!r}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
