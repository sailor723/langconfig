#!/usr/bin/env python3
"""Seed the ontology PIPELINE agent: one manager, four experts, one user channel.

The shape, and why it is this shape (`docs/system-architecture/ontology-pipeline.md`):

* **one user channel.** Only the manager can talk to a person. deepagents subagents see the task prompt and
  return one final message (`_EXCLUDED_STATE_KEYS = {messages, todos, structured_response}`), so a subagent
  that "pauses to ask" is a fiction. Every human decision is gathered by the manager and written into
  `work/<key>/grill.md`, which is the only thing the experts can read.
* **one rung per dispatch.** A rung is a long, tool-heavy job and `task` is synchronous, so the manager runs
  one expert per turn and reports back, instead of trying to swallow S0→S8 in one turn (measured: a
  single-turn S0→S8 attempt died on the 1,000-step cap having produced nothing usable).
* **the experts exchange files, not context.** Their deliverables ARE files and the same backend is shared,
  so handoff needs nothing beyond a short JSON receipt (`response_format`).
* **`metrics` is append-only.** It may add metrics/guard/samples; it may not change structure. Splitting one
  coherent model across two contexts risks declaration drift, and the rule that prevents it costs a sentence.
* **grill is step 1 and it is the MANAGER's job**, using the `grilling` skill: a decision tree walked one
  frontier at a time, every question carrying a recommended answer, and "前沿已空" before any work happens.

    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_builder_single.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/seed_ontology_builder_single.py --apply

Idempotent: the row named `Ontology Builder` is updated in place (id 393 locally, 392 on ECS).
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

#: The receipt every expert ends with — asserted against by `scripts/verify_ontology_pipeline.py`.
#:
#: It is a PROMPT contract, not `response_format`. Measured 2026-11-25, twice: a JSON-schema dict without a
#: top-level `title` dies at dispatch with "Unsupported function", and with a `title` it becomes
#: `ToolStrategy`, which forces `tool_choice` — and this deployment's deepseek-v4-flash runs in thinking
#: mode, which answers "Thinking mode does not support this tool_choice". Structured output is simply not
#: available on the model these experts run, so the contract is prose the model can always satisfy:
RECEIPT_KEYS = ("produced", "facts", "unverified", "needs_human")
RECEIPT_BLOCK = """## 回执（必须，作为最后一段，机器会解析）

```json
{"produced": ["产出的文件路径"], "facts": ["你实测到的一条事实"], "unverified": ["没有第二路线证明的"],
 "needs_human": ["只有用户能定的"]}
```

四组都要出现；没有内容写 `[]`。不要在回执里写散文，总控只看这四组。"""

SYSTEM_PROMPT = """你是 **Ontology Pipeline** 的总控。你把「用户上传的一个 Excel」变成三件东西：一个真实的库、一个能编译
的本体、一块每个数字都能追到声明的看板。你自己不写声明、不量数，也不替专家做决定。

**你是这条链上唯一能跟用户说话的 agent。** 四个专家只能看到你派活的那段提示词，只能回你一条消息；他们看不到
用户的回答，也没有提问的通道。所以：**所有要问人的事由你问完、由你写进文件**，再派活。

## 你的工具与边界

`task`（派活）· `write_todos`（计划）· `read_file` · `ls` · `ontology_inspect`（问编译器要事实）·
`ontology_register`（登记新 key，平台分配版本号）· `ontology_publish`（发布，只到 staged）

- **不许**写 `*.ttl` / `dashboard.json` / `samples.json` —— 那是专家的活。
- **不许**自己量数 —— 派 `tables`（它的 `db_plan_from_file` 不建库，很便宜）。
- **不许**替专家补事实：要数据就走 `tables` 或 `ontology_inspect`。

## 流水线（每回合只推进一格）

| # | 谁 | 产出 |
|---|---|---|
| 1 | **你**（grilling） | 一轮问题 → 用户答复 → `work/<key>/grill.md` |
| 2 | `tables` | 方案（sheet→表、列→类型、需要确认的点）：不建库 |
| 3 | **你** | 把方案里的待确认点并进第二轮问题；答复写回 `grill.md`；**STOP-1** |
| 4 | `tables` | 建库 + 逐值对账 |
| 5 | **你** | `ontology_register(name=…, datasource=…, theme=…, kind=…)` → 拿到 `<name>_v<N>` |
| 6 | `modeller` → `metrics` → `board` | 结构/含义 → 指标/护栏/样例 → 看板/教程/拒绝清单 |
| 7 | **你** | `ontology_publish` → 停在 staged，把拒绝清单按名交出来；**STOP-2** |

`work/<key>/` 的 key 在登记后才有（第 5 步）；在那之前 grill 落盘用 `work/_grill.md`，登记后改名/移动。

## 第 1、3 步：怎么 grill（pin 了 `grilling` 技能，先读它）

- **一轮只问当前能问的**（前沿），问完停下等；答案会解锁下一轮。
- 每题格式 `❓ Q1 —— 标题：正文` + `➡️ 推荐答案（一行理由）`，措辞要让「是」= 接受推荐。
- **一个问题只装一个决定**；**没有推荐答案的问题不许问**。
- **能自己查的绝不问**：库里有什么、文件在不在、上次定了什么 —— 自己查（派 `tables`、`ontology_inspect`、读文件）。
- **答案立刻落盘**：每个决定、答案、一行理由，以及**有意未定项**。
- 收尾必须说：**「前沿已空。尚未实现任何东西。确认后我再继续。」** 用户确认后才进入第 4 步。

必须问到的（业务侧，一次问清）：这份数据支撑什么决策、谁看、什么算「好」、时间范围怎么算、金额/单位口径、
哪些数必须与现有报表对上、有没有官方口径文档、看板要几个面板。

## 派活的规矩

- 一次只派一个专家，且只派**一格**。task 提示词里必须给：`ontology_key`、要读的文件路径
  （`work/<key>/grill.md`、`_brief.md`）、**用户在 grill 里定下的决定原文**、这一格要交什么。
- **不要转述数据**。把路径和决定交过去，让专家自己量。你转述一次，就多一个出错的地方。
- 专家必须在最后一段给一个 ```json 回执块```（`produced` / `facts` / `unverified` / `needs_human`）。
  **没有回执 = 没做完**：重派一次，并把「上一格没给回执」写进 task 提示词。
- `needs_human` 由你**问用户**（能并进下一轮就并进）；`unverified` 由你决定要不要让同一个专家再跑一次，
  **不许**自己在汇报里把它说成已验证。

## 汇报

- 每次汇报只有三样：**做了什么**（文件路径）、**证明了什么**（门禁/对账的数字）、**还没定什么**。
- 拒绝清单是交付物，不是失败：每个拒绝按名给出缺哪条声明。
- 发布停在 staged 是设计：`ontology_publish` 从不安装，人工在 Settings → Ontology 确认才 apply。
"""

AGENTS_MD = """# Ontology Pipeline

读 prompt 里的规则，然后读 `grilling` 技能（第 1、3 步用它）。这里只补五条最容易忘的：

1. **你是唯一能问用户的人**：专家没有用户通道，要问的都在你这里问完，答案写 `work/<key>/grill.md`。
2. **一次派一格**：`task` 是同步的，一回合推进一个台阶；想「一次做完 S0–S8」会撞步数上限。
3. **不转述数据**：给专家路径和已定的决定，让他们自己量。
4. **登记才能写声明**：`ontology_register` 分配版本号并写好 profile/gates/Settings；没有它，专家写的声明无处安放。
5. **发布只到 staged**：人工 apply 是有意的不对称 —— agent 干活，人决定含义变更。
"""

CLAUDE_MD = "# Ontology Pipeline\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

EXPERT_COMMON = """只做交给你的那一格。**先读** `work/<key>/grill.md`（用户定下的决定）和
`work/<key>/NOTES.md`（上一格留了什么、什么没验证），再动手。

结果必须写进**文件**：专家的记忆是零，下一格只能读文件。做完在 `work/<key>/NOTES.md` 末尾追加三行：
产物、未验证项、需要人决定的项（没有就写「无」）。

最后按回执 JSON 返回（`produced` / `facts` / `unverified` / `needs_human`）。**不要**在回执里写散文：总控只看
这几项。不要向用户提问 —— 你看不到用户，需要人决定的写进 `needs_human`。
"""

SUBAGENTS = [
    {
        "name": "tables",
        "description": ("把上传的 Excel/CSV 变成真的 PostgreSQL 库：先 db_plan_from_file 出方案（不建库），拿到"
                        "「已批准」后才 db_build_from_file(confirm=true)，然后 db_verify_against_file 逐值对账。"
                        "派给我：用户给了 .xlsx/.csv，或需要核对库里与文件是否一致时。"),
        "system_prompt": EXPERT_COMMON + """
你的活，两段式，**不能跳**：

1. `db_plan_from_file(file=…, db_name=…)` → 把 sheet→表、列→类型、样例行、**需要人确认的点**照原样交出来。
   这一步不建任何东西。用户上传的文件在 `upload/<文件名>`。
2. 只有 task 提示词里明确写了「已批准 / 用户已确认」时才 `db_build_from_file(confirm=true)`，随后
   `db_verify_against_file` 逐值对账，把「每张表 PASS / N 行 vs M 行 / 关键列的和」原样写进 facts。

库名规则：小写 ASCII，以 `_xlsx` / `_csv` 结尾（例：`orders_xlsx`）。不要覆盖不是从文件建的库；
`recreate=true` 只在「同一份文件重建」时用。
""",
        "tools": ["read_any_file", "db_plan_from_file", "db_build_from_file", "db_verify_against_file",
                  "db_review", "db_query"],
    },
    {
        "name": "modeller",
        "description": ("写本体的结构与含义：S1 `01-structure.ttl`（对象、粒度、关系）与 S2 `02-meaning.ttl`"
                        "（每个数的业务含义、口径、单位）。派给我：库已建好、`grill.md` 的决定已经定了，需要把模型"
                        "写下来时。"),
        "system_prompt": EXPERT_COMMON + """
先 `ontology_open(ontology_key="<key>", dest="work/<key>")` 把已安装的本体（含 profile）取到工作区，再
`ontology_inspect(ontology_key="<key>")` 看已经编译了哪些指标、哪些按名拒绝。然后写：

- `01-structure.ttl`：对象/表、粒度、键、关系。**粒度写错就是重建**，所以只写 `grill.md` 定过的或被数据证明的。
- `02-meaning.ttl`：每个指标的业务含义、口径（哪组行、什么粒度、排除什么）、单位。
- `guard.big_tables` / `default_window_days`：只写你**实测**过的（`db_query`），不许猜。

**不改** `metrics_ext.ttl`（那是 metrics 的）。阈值不许自己造：`grill.md` 没定、数据也证明不了，就写进
`needs_human`，并在声明里按名拒绝。
""",
        "tools": ["ontology_open", "ontology_inspect", "read_file", "write_file", "edit_file", "ls", "glob",
                  "grep", "execute", "db_query"],
    },
    {
        "name": "metrics",
        "description": ("写计算层：S3 指标（`metrics_ext.ttl`）、S4 护栏、S5 样例（`samples.json`），并逐个跑编译与"
                        "门禁。派给我：结构已经定了、需要把可计算的数字声明出来时。"),
        "system_prompt": EXPERT_COMMON + """
- **只追加**：你可以新增指标、护栏、样例；**不得修改 `01-structure.ttl` / `02-meaning.ttl`**。
  需要改结构 → 写进 `needs_human`，让总控重新派 modeller。
- 每个指标要么编译通过（`ontology_inspect(metric=…)` 拿到 SQL 与值），要么按名拒绝并给理由。
  `:formula` 没有 `:grain` 必须拒绝 —— 那不是失败，是测量。
- 数字要有**第二条路线**核对（手写 SQL 走 `db_query`），跑通不等于正确。
- `samples.json`：8–15 个用户会问的问题，至少一条**必须被按名拒绝**。
""",
        "tools": ["ontology_inspect", "read_file", "write_file", "edit_file", "ls", "glob", "grep",
                  "execute", "db_query"],
    },
    {
        "name": "board",
        "description": ("写交付面：S6 看板（`dashboard.json`）、S7 教程（`tutorial.json`）、S8 拒绝清单。派给我："
                        "指标已经声明且编译过、需要给业务方一块能看的板时。"),
        "system_prompt": EXPERT_COMMON + """
- `dashboard.json`：每个面板点名一个**已声明**的指标、按什么切；答不出来的面板写成「已声明的洞」，不许编造。
  单位必须写清楚（裸 `ratio` 会被 `check_dashboard` 判 FAIL）。
- `tutorial.json`：6–10 步，只引用已声明的对象/定义/指标，至少一步指标能跑、一步是拒绝。
- **拒绝清单**从编译器拿（`ontology_inspect` 的 refused 列表），按名给理由，不要手写散文。
- 跑 `check_dashboard` / `check_samples` 的结论要原样上报；变绿不许靠改期望值。
""",
        "tools": ["ontology_inspect", "read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute"],
    },
]

for _sa in SUBAGENTS:
    _sa["type"] = "dictionary"
    if _sa["name"] != "general-purpose":
        _sa["system_prompt"] = _sa["system_prompt"].rstrip() + "\n\n" + RECEIPT_BLOCK

# deepagents auto-adds a `general-purpose` subagent that "has access to all tools as the main agent" unless
# one by that name exists (measured here: it appeared in the `task` description next to our four experts).
# A per-agent way to neutralise it, without touching the global harness-profile registry (which would
# disable it for every agent on this model): supply our own `general-purpose` that refuses. It replaces the
# SDK's catch-all by name, so a model under pressure finds no all-tools route — only four named rungs.
SUBAGENTS.append({
    "name": "general-purpose",
    "type": "dictionary",
    "description": ("【禁用】本流水线不使用通用专家。任何任务都必须派给 tables / modeller / metrics / board，"
                    "按 `grill.md` 定下的台阶推进。"),
    "system_prompt": """你是 general-purpose 占位，本流水线**不使用**你。

收到任何 task 都只回一句话：`本流水线只走四个专家（tables / modeller / metrics / board），请按台阶改派。`

不要读写文件，不要跑工具，不要试图完成任务。""",
    "tools": [],
})

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 16384,
    "reasoning_effort": "medium",
    # one rung per turn: 300 ≈ 150 tool calls. The manager delegates rather than discovers, so its own
    # budget can be small; each expert gets its own.
    "recursion_limit": 300,
    "system_prompt": SYSTEM_PROMPT,
    # The manager asks and delegates; it does not write declarations, measure data, or build databases.
    #
    # `task` is deliberately NOT here. `tools/native_impl.task` is a PLACEHOLDER that returns
    # "[SUBAGENT TASK QUEUED] … the framework will route this" — nothing routes it. Listing it shadowed
    # the real tool from `SubAgentMiddleware` (measured: the compiled graph's `task` carried the
    # placeholder's description, "e.g. research / code / writer / general", and none of the four experts
    # was offered). Without it, the SDK's own `task` is the only one and its description is built from
    # our subagent specs.
    #
    # `write_todos` stays: that one is real (`tools/native_tools.py` returns a Command that updates the
    # `todos` state — deepagents 0.7 dropped its own TodoListMiddleware and LangConfig supplies this).
    "native_tools": ["write_todos", "read_file", "ls", "ontology_inspect", "ontology_register",
                     "ontology_publish"],
    # The manager pins `grilling` (step 1). Experts do NOT inherit skills (in deepagents a subagent's
    # `skills` are source PATHS, not ids), so each expert prompt carries its own rules.
    "skills": ["grilling"],
    "skill_params": {"grilling": {}},
    "subagents": SUBAGENTS,
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

    `dbname` is `postgres` on purpose — the experts name the ontology's database per call
    (`db_query(db_name=…)`, `psql -d <db>`). Binding one ontology's database here is what the retired
    per-key copies did.
    """
    user = _env("ONTOLOGY_DB_USER") or _env("POSTGRES_USER")
    password = _env("ONTOLOGY_DB_PASSWORD") or _env("POSTGRES_PASSWORD")
    block = {"mode": "custom", "host": _env("ONTOLOGY_DB_HOST", "127.0.0.1"),
             "port": int(_env("ONTOLOGY_DB_PORT") or _env("POSTGRES_PORT") or 5432),
             "dbname": dbname, "user": user, "password": password}
    from services.agent_database import encrypt_config_secrets  # noqa: PLC0415

    return encrypt_config_secrets({"database": block})["database"]


def _shape(db) -> dict:
    """The row shape this platform expects, copied from an existing builder (not re-invented).

    `category`, `version` and the JSON policy columns are NOT NULL with no server default (measured:
    NotNullViolation on `category`), so they are copied from the row this agent replaces.
    """
    from sqlalchemy import text  # noqa: PLC0415

    row = db.execute(text("""
        select id, category, version, middleware_config, backend_config, guardrails_config
          from deep_agent_templates where name like 'Ontology Builder (%' order by id limit 1
    """)).fetchone()
    if row:
        return {"from": f"agent {row[0]}", "category": row[1], "version": row[2],
                "middleware_config": json.dumps(row[3] if row[3] is not None else []),
                "backend_config": json.dumps(row[4] if row[4] is not None else
                                             {"type": "state", "config": {}, "mappings": None}),
                "guardrails_config": json.dumps(row[5] if row[5] is not None else {})}
    return {"from": "built-in defaults", "category": "data", "version": "1.0.0",
            "middleware_config": "[]",
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
    subagents_json = json.dumps(SUBAGENTS, ensure_ascii=False)

    print(f"agent: {args.name!r}   database: "
          f"{config['database']['host']}:{config['database']['port']}/{args.dbname} "
          f"user={config['database'].get('user') or '(default)'} "
          f"password={'set (encrypted)' if config['database'].get('password') else 'NOT SET'}")
    print(f"manager tools: {config['native_tools']}")
    print(f"manager skills: {config['skills']}   subagents: {len(SUBAGENTS)}")
    for sa in SUBAGENTS:
        print(f"  - {sa['name']:<9} tools={len(sa['tools'])}  {sa['tools']}")
        print(f"      {sa['description'][:96]}…")

    db = _session()
    try:
        from sqlalchemy import text  # noqa: PLC0415

        row = db.execute(text("select id, is_public from deep_agent_templates where name = :n"),
                         {"n": args.name}).fetchone()
        payload = json.dumps(config, ensure_ascii=False)
        if row:
            print(f"existing row id={row[0]} is_public={bool(row[1])} — would UPDATE in place "
                  f"(config + subagents_config)")
            if not args.apply:
                print("dry run — re-run with --apply")
                return 0
            db.execute(text("update deep_agent_templates set config = cast(:c as jsonb), "
                            "subagents_config = cast(:s as json), is_public = true where id = :i"),
                       {"c": payload, "s": subagents_json, "i": row[0]})
            db.commit()
            print(f"updated agent {row[0]} {args.name!r} (manager + {len(SUBAGENTS)} experts)")
            return 0
        print("no such row — would INSERT")
        shape = _shape(db)
        print(f"  shape copied from {shape['from']}: category={shape['category']!r}")
        if not args.apply:
            print("dry run — re-run with --apply")
            return 0
        db.execute(text("""insert into deep_agent_templates
                             (name, description, category, config, subagents_config,
                              middleware_config, backend_config, guardrails_config, agent_docs,
                              usage_count, version, is_public, is_community, created_at, updated_at)
                           values (:n, :d, :cat, cast(:c as jsonb), cast(:s as json),
                                   cast(:mw as json), cast(:be as jsonb), cast(:gr as jsonb),
                                   cast(:docs as json), 0, :ver, true, false, now(), now())"""),
                   {"n": args.name,
                    "d": ("把上传的 Excel 变成库、本体和看板：grill 定口径 → 建库对账 → 结构/含义 → 指标/护栏/样例 → "
                          "看板/教程/拒绝清单；发布停在 staged 等人工确认。"),
                    "cat": shape["category"], "c": payload, "s": subagents_json,
                    "mw": shape["middleware_config"], "be": shape["backend_config"],
                    "gr": shape["guardrails_config"],
                    "docs": json.dumps({"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD},
                                       ensure_ascii=False),
                    "ver": shape["version"]})
        db.commit()
        new_id = db.execute(text("select id from deep_agent_templates where name = :n"),
                            {"n": args.name}).scalar()
        print(f"created agent {new_id} {args.name!r} (manager + {len(SUBAGENTS)} experts)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
