#!/usr/bin/env python3
"""Seed the ONE ontology builder agent — `Ontology Builder`, without an ontology baked in.

Measured 2026-11-12: seven builder rows existed, each a copy of this same prompt with an ontology key
and a database hardcoded in four places (agent name, the `skill_params`, the dsn line, the "you only
touch X" rule). Two of them had already drifted a tool short of the rebuild path. This script writes
the single row those copies were converging on:

* **no `ontology_key` anywhere in the row.** The key arrives in the conversation (the customer says a
  name; the platform assigned `<name>_v<N>` — see `features/ontology/versioning.py`), so a new
  ontology does not need a new agent.
* **one database binding, the ontology server itself.** `config.database` is a custom block pointing
  at the server that holds every ontology database (`dbname` defaults to `postgres`); the agent names
  the target database per task (`psql -d <db>`), which is what makes one agent able to serve many
  ontologies. `db_query` therefore still measures — it is bound to that server, not to one database.
* **the 11-tool superset**, so the rebuild path (`ontology_open`, `read_any_file`) is present.

The password is stored encrypted (the same path the UI uses) and never appears in the prompt.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_builder_single.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_builder_single.py --apply

Idempotent: an existing row with this name is updated in place.

After this, `retire_ontology_builders.py --require-target --apply` hides the per-key copies.
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

NAME = "Ontology Builder"

SYSTEM_PROMPT = """你是 **Ontology Builder**：把一个**已经存在的 PostgreSQL 库**变成一套**声明**，让每个数字
都能被编译、被拒绝、被复核。你不发明口径，也不直接改已安装的本体——你写文件，跑闸门，通过发布通道提交。

**你一次只服务一个本体，但你可以服务任何本体。** 本体 key 不在你身上：用户第一条消息会给出它（形如
`sunhing_v2`、`new_coldchain_v8`）。没有 key 就先问清楚——不要猜，也不要自己起名：名字是客户说的，版本号
是平台按 `<名字>_v<N>` 分配的，一个已经存在的 key 代表一份已经发布的声明，写错位置等于改别人正在用的数字。

## 你要弄清楚的三个事实（弄不清就问，不要编）

- **ontology_key**：这次要写哪一份本体（`<key>/01-structure.ttl`、`02-meaning.ttl`、`metrics_ext.ttl`、
  `<key>_settings.json`、`samples.json`、`tutorial.json`、`dashboard.json`）。
- **datasource**：这个 key 对应的 PostgreSQL 库名。库名在 `profiles/<key>/<key>_settings.json` 的
  `dsn.dbname` 里，读它，不要从 key 猜。**你的连接默认落在 `postgres` 库，不是本体的库**：
  `db_query(db_name="<库名>", …)` 按名字连任意库；`execute` 里的 psql 一律显式 `-d <库名>`。
- **客户/运维签过的事实**：`profiles/<key>/_brief.md` 若存在，先读它（主题、库名、口径偏好、已知缺口）。
  它和 profile 一样是**输入**，不是你该写的东西。

## dsn 怎么写

`<key>_settings.json` 里的 dsn 必须是可部署的形式：host/port/user/password 一律引用宿主注入的变量，
不许出现字面量口令（门禁 X2 会拒）。照抄同目录 profile 里已经在用的那一行，只把 `dbname` 换成这个库：

```json
"dsn": {"host": "${ONTOLOGY_DB_HOST:-127.0.0.1}", "port": "${ONTOLOGY_DB_PORT:-5432}",
        "dbname": "<库名>", "user": "${ONTOLOGY_DB_USER}", "password": "${ONTOLOGY_DB_PASSWORD}"}
```

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

- 声明写在你 workspace 的 `<key>/` 目录，然后调用 **`ontology_publish(ontology_key="<key>", source_dir="<key>", note="…")`**。
  它会：把文件覆盖到已安装本体的暂存副本、逐个编译每个指标、跑通用闸门，把报告返回给你。
  **新增的拒绝、失败的闸门，都会让这次发布在暂存阶段被拒**——已经存在的拒绝会单独列成"carried"，那不算你的。
- `ontology_publish` **从不安装**。它停在 `staged`；一个有人类角色的账号在 Settings → Ontology 里确认后
  才会 apply（apply 会再跑一遍闸门、再编译一遍、字节级备份后提交）。
- **不要**直接写 `backend/features/ontology/profiles/`（那不是你的 workspace，也不该由你写）。
- 交付时必须给：编译/拒绝清单（每个拒绝按名给原因）、闸门结果、`dashboard.json`/`samples.json`/`tutorial.json`
  是否存在、以及一句话"这个本体现在能回答什么、不能回答什么"。
- 最后附一份给运维的清单：`gates.json` 里为这个 key 新增一条声明（standalone/profile 哪些族）；
  在运维补上之前，`scripts/ontology_gates.py` 会把整个仓库判红——那是设计，不是 bug。

## 一个 key 第一次出现时

如果用户给的名字**还没有**对应的 profile 目录，说明它还没登记：告诉他运维要先跑
`add_ontology_builder.py --base <名字> --datasource <库> --no-agent`（平台会给出版本号、写 gates/Settings/.env
和版本登记）。目录存在（哪怕只有 `_brief.md`）才开始写声明。**不要自己创建 profile 目录。**

## 硬规则

- **一轮只做一级台阶**。S0 出完三件产物就停；S1 写完 TTL + 跑出门禁数字就停。想"一次做完 S0→S8"
  的回合会在步数上限上撞死（实测 1 183 次工具调用、1 042 次 `execute`，一步产物都没换到）。
- **量库用 `db_query`，一次调用把整批 SELECT 发过去**：`db_query(db_name="<库名>", sqls=[...])`，
  最多 20 条，一条连接一次往返。**不要用 `execute` 跑 `psql` 量数**——那是一次 shell 换一次模型往返
  （实测 1 618 次 `execute` 花了 6 085 秒，而每条查询本身是毫秒级）。库的形状一次
  `db_query(db_name="<库名>", sql="select relname, n_live_tup from pg_stat_user_tables order by 2 desc")`。
  口令不是参数：`db_query` 用你自己 Database 配置里的凭据。
- **不要读平台代码**（`compiler/`、`gates/`、`skills/` 的实现）。要看口径就跑门禁命令、读它自己的输出；
  读平台代码是 DSH 的活。
- **声明是唯一真相**。不要在 SQL 里手算一个数再写进断言；不要为了让闸门变绿去改期望值。
- **没有对应字段的能力**，写进拒绝清单（`:physicalPredicate` 是唯一逃生口，且必须注释说明），
  不要造代理列让 demo 看起来完整。
- **指标必须先编译或按名拒绝**；`:formula` 没有 `:grain` 必须拒绝，那不是失败，是测量。
- 数字要有**第二条手写 SQL 路线**核对（`--trust`/`truth.json`），跑通不等于正确。
- 你只碰目标库的**只读**查询；写入只能是通过本体声明的 action（如果业务真的需要）。
"""

AGENTS_MD = """# Ontology Builder

读 prompt 里的规则，然后读 `build-ontology-from-db` 的 SKILL.md。这里只补四条最容易忘的：

1. **key 是用户给的，版本号是平台给的**。不知道 key 就问；不要自己起名，也不要改别人已经发布的 key。
2. **默认库是 `postgres`**：量库、跑脚本一律显式 `-d <库名>`，库名从 profile 的 `dsn.dbname` 读。
3. **两个停点要真的停**：模型草图、定义含义。别用"我先写着看"跳过。
4. **拒绝清单是交付物**，不是失败。每个拒绝按名说清楚缺哪条声明。
"""

CLAUDE_MD = "# Ontology Builder\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 16384,
    "reasoning_effort": "medium",
    # one ladder rung per turn: 300 is ~150 tool calls — see seed_ontology_build_agent.py for the
    # measurement (a single-turn S0→S8 attempt died on the 1 000-step cap with nothing to show)
    "recursion_limit": 300,
    "system_prompt": SYSTEM_PROMPT,
    # the 11-tool superset: `ontology_open` is the rebuild path (open an INSTALLED ontology as a
    # workspace copy) and `read_any_file` reads a user-supplied brief; the six per-key copies split
    # 9 vs 11, and the 9-tool ones could not rebuild at all.
    "native_tools": ["read_file", "read_any_file", "write_file", "edit_file", "ls", "glob", "grep",
                     "execute", "db_query", "ontology_open", "ontology_inspect", "ontology_publish"],
    "skills": ["build-ontology-from-db"],
    # NO ontology_key and NO datasource: the key arrives per conversation, the database is the
    # ontology server (config.database). A baked default here is exactly what made seven copies.
    "skill_params": {"build-ontology-from-db": {}},
    "use_deepagents": True,
    "use_local_sandbox": True,
}


def _env(name: str, default: str = "") -> str:
    """A value from the environment, then the repo `.env` (this may run without the app loaded)."""
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
    """The ontology server as this agent's database: host/port/user + encrypted password.

    `dbname` is `postgres` on purpose — the agent names the ontology's database per task. Binding one
    ontology's database here is what the retired per-key copies did.
    """
    user = _env("ONTOLOGY_DB_USER") or _env("POSTGRES_USER")
    password = _env("ONTOLOGY_DB_PASSWORD") or _env("POSTGRES_PASSWORD")
    block = {"mode": "custom", "host": _env("ONTOLOGY_DB_HOST", "127.0.0.1"),
             "port": int(_env("ONTOLOGY_DB_PORT") or _env("POSTGRES_PORT") or 5432),
             "dbname": dbname, "user": user, "password": password}
    from services.agent_database import encrypt_config_secrets  # noqa: PLC0415

    cfg = encrypt_config_secrets({"database": block})
    return cfg["database"]


def _shape(db) -> dict:
    """The row shape this platform expects, copied from an existing builder (not re-invented).

    `category`, `version` and the four JSON policy columns are NOT NULL with no server default: a row
    inserted without them is rejected by Postgres (measured: NotNullViolation on `category`). Copying
    them from the agent this one replaces keeps guardrail/token limits in one place.
    """
    from sqlalchemy import text  # noqa: PLC0415

    row = db.execute(text("""
        select id, category, version, middleware_config, subagents_config, backend_config,
               guardrails_config
          from deep_agent_templates where name like 'Ontology Builder (%' order by id limit 1
    """)).fetchone()
    if row:
        return {"from": f"agent {row[0]}", "category": row[1], "version": row[2],
                "middleware_config": json.dumps(row[3] if row[3] is not None else []),
                "subagents_config": json.dumps(row[4] if row[4] is not None else []),
                "backend_config": json.dumps(row[5] if row[5] is not None else
                                             {"type": "state", "config": {}, "mappings": None}),
                "guardrails_config": json.dumps(row[6] if row[6] is not None else {})}
    return {"from": "built-in defaults", "category": "data", "version": "1.0.0",
            "middleware_config": "[]", "subagents_config": "[]",
            "backend_config": json.dumps({"type": "state", "config": {}, "mappings": None}),
            "guardrails_config": json.dumps({"interrupts": {}})}


def _session():
    from db.database import SessionLocal  # noqa: PLC0415

    return SessionLocal()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=NAME, help=f"agent name (default: {NAME!r})")
    ap.add_argument("--dbname", default="postgres",
                    help="the database bound to the agent (default: postgres, i.e. 'name one per task')")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    config = {**CONFIG, "database": database_block(args.dbname)}
    print(f"agent: {args.name!r}   database: "
          f"{config['database']['host']}:{config['database']['port']}/{args.dbname} "
          f"user={config['database'].get('user') or '(default)'} "
          f"password={'set (encrypted)' if config['database'].get('password') else 'NOT SET'}")
    print(f"tools: {len(config['native_tools'])}  skills: {config['skills']}  "
          f"skill_params: {json.dumps(config['skill_params'], ensure_ascii=False)}")

    db = _session()
    try:
        from sqlalchemy import text  # noqa: PLC0415

        row = db.execute(text("select id, is_public from deep_agent_templates where name = :n"),
                         {"n": args.name}).fetchone()
        payload = json.dumps(config, ensure_ascii=False)
        if row:
            print(f"existing row id={row[0]} is_public={bool(row[1])} — would UPDATE in place")
            if not args.apply:
                print("dry run — re-run with --apply")
                return 0
            db.execute(text("update deep_agent_templates set config = cast(:c as jsonb), "
                            "is_public = true where id = :i"), {"c": payload, "i": row[0]})
            db.commit()
            print(f"updated agent {row[0]} {args.name!r}")
            return 0
        print("no such row — would INSERT")
        shape = _shape(db)
        print(f"  shape copied from {shape['from']}: category={shape['category']!r} "
              f"version={shape['version']!r}  (guardrails/middleware/backend defaults stay in one place)")
        if not args.apply:
            print("dry run — re-run with --apply")
            return 0
        db.execute(text("""insert into deep_agent_templates
                             (name, description, category, config, middleware_config,
                              subagents_config, backend_config, guardrails_config, agent_docs,
                              usage_count, version, is_public, is_community, created_at, updated_at)
                           values (:n, :d, :cat, cast(:c as jsonb), cast(:mw as json), cast(:sub as json),
                                   cast(:be as jsonb), cast(:gr as jsonb), cast(:docs as json),
                                   0, :ver, true, false, now(), now())"""),
                   {"n": args.name,
                    "d": ("服务任何一个本体：key 由对话给出，库名从 profile 读；结构/含义/计算三层声明 + "
                          "护栏 + 闸门 + 菜单/教程/拒绝清单，通过 ontology_publish 停在 staged 等人类确认。"),
                    "cat": shape["category"], "c": payload,
                    "mw": shape["middleware_config"], "sub": shape["subagents_config"],
                    "be": shape["backend_config"], "gr": shape["guardrails_config"],
                    "docs": json.dumps({"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD},
                                       ensure_ascii=False),
                    "ver": shape["version"]})
        db.commit()
        new_id = db.execute(text("select id from deep_agent_templates where name = :n"),
                            {"n": args.name}).scalar()
        print(f"created agent {new_id} {args.name!r}")
        print("next: retire the per-key copies → "
              "scripts/seeds/in/retire_ontology_builders.py --require-target --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
