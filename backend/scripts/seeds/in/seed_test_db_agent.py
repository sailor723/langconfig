#!/usr/bin/env python3
"""Seed `test_db` — the smallest possible database agent: ONE tool, `db_query`, and nothing else.

Purpose: a probe you can configure and poke without a pipeline in the way. It exists to answer "does an
agent plus a Database setting actually reach the databases on this box?" — so it has:

* **one tool.** `db_query` (read-only SELECT, any database by name, batched `sqls=[…]`). No DDL, no writes,
  no filesystem, no subagents — if something fails here, it is the tool or the connection, not the design.
* **no deep agent.** `use_deepagents: false`: a plain `create_agent` loop. Faster to build, nothing to
  assemble, and no sandbox to misconfigure.
* **a Database setting.** `config.database` is a custom block (host/port/user + encrypted password,
  `dbname=postgres`). That is where the credential comes from — `db_query` takes a database NAME, never a
  password, and the connection details reach the tool as PGPASSWORD. Configure it in the agent editor
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

SYSTEM_PROMPT = """你是 **test_db**：一个用来试数据库连接的最小 agent。你只有一个工具 `db_query`（只读 SELECT）。

## 怎么用

- **`db_query(db_name="<库名>", sql="<一条 SELECT>")`** —— 查一个库；要量多个口径时用
  **`db_query(db_name="<库名>", sqls=["…", "…"])`**，一次调用一条连接、一次往返拿回全部结果。
- **库名必须显式给**（你不知道服务器上有哪些库时，直接问用户，或让用户跑 `DB Manager` 的 `db_list_databases`）。
- 只读：本 agent 没有任何写工具。要坚持改数据，请用 `DB Manager（数据库管理）` 的 `db_execute`。

## 连接从哪来

你的连接来自 **Agent → Database 这一项设置**（host / port / user / 加密口令），`db_name` 只指定**哪个库**。
没配 Database 时每次调用都会以 `no password supplied` 之类的方式失败 —— 那是配置问题，不是 SQL 问题。

## 汇报

- 报数就给**数字 + 你实际跑的那条 SQL**（一句），不要只给结论。
- 查询失败就把工具返回的原文贴出来（它通常会说是哪个库/哪张表/哪个列不存在）。
- 不要猜列名：先 `select * … limit 5` 看一眼，或让用户用 `db_describe` 看结构。
"""

AGENTS_MD = """# test_db

只有一个工具：`db_query`（只读，任意库，`db_name` + `sql` / `sqls`）。

1. 库名要显式给；服务器上有哪些库不是本 agent 能列出来的（那是 `db_list_databases`）。
2. 连接来自 **Agent → Database** 设置；没配就是配置错误，不是 SQL 错误。
3. 报数带 SQL；失败贴原文。本 agent 不能写数据。
"""

CLAUDE_MD = "# test_db\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 4096,
    "reasoning_effort": "medium",
    "recursion_limit": 60,
    "system_prompt": SYSTEM_PROMPT,
    "native_tools": ["db_query"],
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
    ap.add_argument("--dbname", default="postgres",
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
