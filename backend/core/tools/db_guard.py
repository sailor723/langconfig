"""Refuse shell commands that open a database connection.

The invariant (docs/system-architecture/ontology-agent-boundaries.md): **a database connection may only be
opened by a db tool** — `db_query_agent` (you write the SQL), `db_query_langgraph` (natural language),
`db_execute` (writes). Python itself stays available; what it may not do is connect.

Why a call-time guard and not a tool allowlist: measured 2026-11-25 on agent 393 — `execute` appeared 264
times in one run with four of them running `psql` (`-lqt`, `--version`, `-c "SELECT … information_schema"`),
while the prompt said "don't query the database from the shell". The tools were bound; the shell was simply
a second, unguarded door. Removing `execute` wholesale is not an option (the ontology experts run the repo's
compile/gate scripts with it), so the door stays open and only the database part of it is bolted.

Patterns are matched against the RAW command string and against each line, so both
`psql -c "select 1"` and `python -c "import psycopg2; psycopg2.connect(...)"` are caught, while
`python -m features.ontology.gates.check_structure --profile …` is not.
"""
from __future__ import annotations

import re

#: (regex, 为什么这是"连库") —— 顺序无关，命中任一条即拒。
DB_CONNECTION_PATTERNS: list[tuple[str, str]] = [
    (r"\bpsql\b", "psql 客户端直连"),
    (r"\bpg_dump\b|\bpg_restore\b|\bcreatedb\b|\bdropdb\b|\bpg_isready\b", "PostgreSQL 客户端工具"),
    (r"\bpsycopg2?\b", "驱动直连（psycopg/psycopg2）"),
    (r"\basyncpg\b", "驱动直连（asyncpg）"),
    (r"\bsqlalchemy\b|\bcreate_engine\s*\(", "ORM 直连（sqlalchemy）"),
    (r"\bconnect\s*\([^)]*dbname", "connect(...) 里带 dbname"),
    (r"\bcopy\s+\S+\s+from\s+stdin\b|\bcopy\s+\S+\s+to\s+stdout\b", "COPY 流式读写"),
    (r"PGPASSWORD\s*=", "自己拼 PGPASSWORD"),
    (r"\bpostgres(ql)?://\S+@", "DSN 里带凭据"),
]

_COMPILED = [(re.compile(p, re.I), why) for p, why in DB_CONNECTION_PATTERNS]

REFUSAL = """⛔ 拒绝执行：这条命令会自己打开数据库连接（{why}）。
数据只走三扇门，请改用对应的工具：
  · 已知 SQL（计数/聚合/对账）→ db_query_agent(db_name=…, sql=… / sqls=[…])
  · 不知道表结构或口径 → db_query_langgraph(question=…, database=…)
  · 写（DDL/DML）→ db_execute(db_name=…, sql=…, confirm=…)
  · 看库/表结构 → db_describe() / db_describe(db_name=…) / db_describe(db_name=…, table=…)
python 仍可用于解析文件、算数、生成报告、跑编译与门禁（例如 python -m features.ontology…）——
被拒的只是"用 shell 连库"。
"""


def find_db_connection(command: str) -> str | None:
    """Return why this command counts as a database connection, or None if it does not."""
    if not command:
        return None
    for regex, why in _COMPILED:
        if regex.search(command):
            return why
    return None


def refusal(command: str) -> str | None:
    """The refusal text for a command, or None when the command is allowed."""
    why = find_db_connection(command)
    if why is None:
        return None
    return REFUSAL.format(why=why)
