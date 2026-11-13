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
#: The database NAME the dsn example must carry, when it differs from the datasource's key.
#: Measured on sunhing_v1: the datasource is registered as `sunhing`, the database is
#: `sunhing_kpi`, and the seeded prompt told every later builder to write `dbname: "sunhing"` —
#: a dsn that cannot connect, in the one block people copy verbatim. (Audited by
#: `scripts/audit_agent_prompts.py`, which compares the prompt's dsn against the installed profile.)
DATASOURCE_DB = os.environ.get("DATASOURCE_DB") or DATASOURCE
#: The deployment's connection defaults, so the profile a builder writes RESOLVES on this host instead of
#: pointing at 5432/weiping out of habit. A password is never written: the variable name travels, the
#: value stays in the deployment's .env (gate X2 refuses a literal in a declaration).
PROFILE_DIR = BACKEND / "features" / "ontology" / "profiles" / KEY


def _profile_dsn_defaults() -> dict:
    """port/user/password-var defaults READ FROM the installed profile, when there is one.

    Measured (2026-11-13): `sunhing_kpi` lives on 5433 as `langconfig` while `meeting_hub` lives on
    5432 as `weiping`, so a single global default teaches half the builders a dsn that cannot
    connect — and the disagreement is invisible until someone asks a number. The installed profile
    is the truth about THIS deployment; env still wins, and a brand-new key (no profile yet) falls
    back to the documented defaults.
    """
    for name in (f"{KEY}_settings.json", "settings.json"):
        path = PROFILE_DIR / name
        if not path.exists():
            continue
        try:
            dsn = (json.loads(path.read_text(encoding="utf-8")) or {}).get("dsn") or {}
        except Exception:                                    # noqa: BLE001
            return {}
        out = {}
        for field, env in (("port", "DSN_PORT"), ("user", "DSN_USER")):
            value = str(dsn.get(field) or "")
            value = value.split(":-")[-1].rstrip("}") if ":-" in value else value
            if value:
                out[env] = value
        password = str(dsn.get("password") or "")
        if password.startswith("${") and password.endswith("}"):
            out["DSN_PASSWORD_VAR"] = password[2:-1]
        return out
    return {}


_PROFILE_DEFAULTS = _profile_dsn_defaults()
DSN_PORT = os.environ.get("DSN_PORT") or _PROFILE_DEFAULTS.get("DSN_PORT") or "5432"
DSN_USER = os.environ.get("DSN_USER") or _PROFILE_DEFAULTS.get("DSN_USER") or "weiping"
DSN_PASSWORD_VAR = (os.environ.get("DSN_PASSWORD_VAR")
                     or _PROFILE_DEFAULTS.get("DSN_PASSWORD_VAR")
                     or "ONTOLOGY_DB_PASSWORD")
NAME = os.environ.get("BUILDER_AGENT_NAME") or f"Ontology Builder ({KEY})"
# The description is what a human reads in the agent list, so it must describe the ontology this
# agent actually targets — not the one the database had when the agent was first written down.
# Measured: agent 355 kept saying "16 张表" for months after the demo database grew to 28, and a
# reseed did not correct it because the update path never sent a description.
DESCRIPTION = (f"把 `{DATASOURCE}` 这个库编译成 `{KEY}` 本体：结构/含义/计算三层声明 + 护栏 + "
               "闸门 + 菜单/教程/拒绝清单，通过 ontology_publish 停在 staged 等人类确认。")

SYSTEM_PROMPT = f"""你是 **Ontology Builder ({KEY})**：把一个**已经存在的 PostgreSQL 库**变成一套**声明**，让每个数字
都能被编译、被拒绝、被复核。你不发明口径，也不直接改已安装的本体——你写文件，跑闸门，通过发布通道提交。

## 你负责的本体

- **ontology_key**：`{KEY}`（`{KEY}/01-structure.ttl`、`02-meaning.ttl`、`metrics_ext.ttl`、`{KEY}_settings.json`、
  `samples.json`、`tutorial.json`、`dashboard.json`）
- **datasource**：`{DATASOURCE}` —— 已经绑进沙箱的 `PG*` 环境变量，`psql` 与 psycopg2 不用参数就能连。
- `{KEY}_settings.json` 里的 dsn 请写成可部署的形式（照抄这一行，别改里面的数值；默认值只是本地开发值，
  换一台机器时由宿主注入 `ONTOLOGY_DB_*` 覆盖它，声明里不许出现字面量口令 —— 门禁 X2 会拒）：
  `"dsn": {{"host": "${{ONTOLOGY_DB_HOST:-127.0.0.1}}", "port": "${{ONTOLOGY_DB_PORT:-{DSN_PORT}}}", "dbname": "{DATASOURCE_DB}", "user": "${{ONTOLOGY_DB_USER:-{DSN_USER}}}", "password": "${{{DSN_PASSWORD_VAR}}}"}}`

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

- **一轮只做一级台阶**。S0 出完三件产物就停；S1 写完 TTL + 跑出门禁数字就停。想"一次做完 S0→S8"
  的回合会在步数上限上撞死（实测 1 183 次工具调用、1 042 次 `execute`，一步产物都没换到）。
- **量库用 `db_query`，一次调用把整批 SELECT 发过去**（`sqls=[...]`，最多 20 条，一条连接一次往返）。
  **不要用 `execute` 跑 `psql` 量数**——那是一次 shell 换一次模型往返（实测 1 618 次 `execute` 花了
  6 085 秒，而每条查询本身是毫秒级）。库的形状一次 `db_query(sql="select relname, n_live_tup from
  pg_stat_user_tables order by 2 desc")`；口径验证一次 `db_query(sqls=[口径1, 口径2, …])` 拿回全部结果。
  `execute` 只留给 DDL/DML（建视图、改表）和跑门禁命令。
- **不要读平台代码**（`compiler/`、`gates/`、`skills/` 的实现）。要看口径就跑门禁命令、读它自己的输出；
  读平台代码是 DSH 的活。
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
    # ONE LADDER STEP PER TURN. LangGraph's default is 150 and a v6 build hit it mid-ladder, so this
    # was raised to 1000 — and that taught the builder to attempt the whole S0→S8 ladder in one turn.
    # Measured on ebl_ops_v1 (2026-11-14): 1 183 tool calls in a single turn, of which 1 042 were
    # `execute` (one query per shell call instead of one profiling query), and the turn died on the
    # 1 000-step cap having produced nothing usable. 300 is ~150 tool calls: enough for one rung
    # (write the declarations, run its gate, fix what the gate names), and small enough that hitting
    # the cap is a signal to split the work rather than a way to burn an hour.
    "recursion_limit": 300,
    "system_prompt": SYSTEM_PROMPT,
    # `read_any_file` so a user-supplied brief/spec (PDF/DOCX/PPTX) can be read from upload/, not guessed at.
    # `execute` runs the skill's scripts (introspect_db.py / scaffold_ttl.py / check_ontology.py), DDL/DML
    # and the gate commands. `db_query` is for MEASURING: it takes a batch of read-only SELECTs and
    # returns every result in ONE round-trip. Measured 2026-11-14 (agent 380): 1 618 separate `execute`
    # Psql calls = 6 085 s of wall clock at ~4 s per model round-trip, while the queries themselves ran
    # in milliseconds — the round-trip, not the SQL, was the cost.
    # `ontology_open` is what turns an ALREADY INSTALLED ontology into a workspace copy to extend —
    # the rebuild path (skill S-1) that v6 and every successor need. Without it an agent asked to
    # extend an installed ontology either refuses or copies the repo with `cp -r` through `execute`,
    # which skips the profile facts the tool prints and edits a tree it does not own.
    "native_tools": ["read_file", "read_any_file", "write_file", "edit_file", "ls", "glob", "grep",
                     "execute", "db_query", "ontology_open", "ontology_inspect", "ontology_publish"],
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
    _call("PUT", f"/api/deepagents/{agent_id}",
          {"config": cfg, "agent_docs": docs, "description": DESCRIPTION})

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
