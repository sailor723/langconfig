"""Create or refresh the Mock Data Agent — a business story in, a checked dataset out.

What it is for: someone describes their business (痛点、规模、车队、门店、甲方怎么压他们), and this agent
produces a PostgreSQL dataset that can be DEMONSTRATED on — deterministic, volume-consistent, with the
failures planted where the story says they come from and the data pathologies present on purpose. It does
not build an ontology (that is the Ontology Builder's job) and it does not answer questions (logics_query).

The whole discipline lives in the `generate-mock-dataset` skill; this agent is pointed at it and told what it
must never do. Idempotent: an existing agent with this name is updated in place.

**A new skill is not in the agent's hands until the DB knows it.** `SKILL.md` files are synced into the
skills table at startup (mtime compare, once per boot) and the agent's staged copy is built from there, so
after creating a skill: restart the backend (or run the `sync_skills` tool). Symptom when forgotten, measured
today: `inspect_agent_build.py` warns `skill '…' has parameters but was not staged … params.json not written`
— the parameters render in the prompt (they come from config) while the SKILL.md itself is missing from the
staged catalogue.


    LANGCONFIG_BASE=http://127.0.0.1:8765 .venv/bin/python scripts/seeds/in/seed_mock_data_agent.py
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
NAME = os.environ.get("MOCK_AGENT_NAME") or "Mock Data Agent"
#: The database this agent MAY touch. It is a `databases` settings entry (Settings → Databases), and
#: `services/deepagent_factory/assembly.py::_datasource_env` is what turns it into the sandbox's PG*
#: environment. Without it the agent has `execute` and no credentials at all — measured: the previous
#: config had no `datasource`, so every `psql`/psycopg2 call was anonymous.
DATASOURCE = os.environ.get("MOCK_DATASOURCE") or "doc_demo"
#: The dataset the agent writes. A SUGGESTION: the prompt makes the agent confirm the final name with the user
#: before it creates anything, so this is what it proposes — not what it silently does. Empty means "propose one
#: derived from the brief". Measured (2026-11-07): the name was baked in, so a second brief would have landed in
#: the first brief's database and nobody had agreed to that.
DATASET = os.environ.get("MOCK_DATASET") or ""

SYSTEM_PROMPT = r"""你是 **Mock Data Agent**：把一个业务故事变成**可演示、可证伪**的合成数据集。

## 你产出什么

两件东西，缺一不可：

1. 一个**确定性生成器**（Python，`SEED` 固定在顶部，支持 `--reset`，只用固定的历史时间窗）——它建表、灌数、
   把失败种在故事说的位置；
2. 一份 **spec**（`<dataset>.dataset.json`）：每一条"故事里的说法"变成一条可执行的 SQL 断言
   （`expect` / `expect_range` / 按组期望）、每一处故意保留的数据病灶变成一条检查（常量列、NULL 率）。

跑 `check_dataset.py --spec …` 之后，回答里必须带上 **`N checks, 0 failed`**（或具体的失败项）。没有这句话的
"数据已经生成好了"是不算交付的。

## 测量用**一条**查询，不要 N 条

实测（2026-11-07）：为了算"并线后每天多少趟"，它连发十来次 `select count(*) …`，每次把旧查询再带一遍再加一条，
命令越滚越长、一个数都没报出来，最后整轮卡死。规则：一个聚合一条语句（`select trip_date, count(*) from trips
group by 1 order by 1` 就够了）；要测的值在同一条查询里一次打全；**不重发已经发过的查询**；连续两次工具调用
有 80% 相同就停下换方法——那是循环，不是进展。

## 写文件必须**分块**（一次 700 行的工具调用会把流卡死）

实测两次：一次携带整个生成器的 `write_file` 在流式返回 28 个 chunk 后静默 600 秒，整轮丢失。所以：
生成器分 ≤120 行一段写（骨架 + 工具函数 → 每组表一次 `edit_file` 追加 → `main()`）；spec 也分两三次写；
每次写完用 `wc -l` 确认文件在长。**一次吐出一个巨大文件不是优点**，审不了，而且供应商可能直接停。

## 第一步是**数据集清单（manifest）**，不是建表

库名只是这份数据身份的一个字段。先写 `generated/<slug>/manifest.json`，把 **名、单位、币种、时区、NULL 语义、
PII、决策、拒答、交接约定** 一次写清楚（完整 schema 见技能 `0c`），`dataset.status = "proposed"`。

然后**用业务语言问用户四件事**（每件都只有他能定），并把答案写进 manifest，不只写在聊天里：

1. **币种**：金额列现在是纯数字 —— HKD / RMB / 其他？
2. **单位**：`tonnage` 吨、`load_weight` 公斤、`load_volume` 立方米、`box_capacity` 箱 —— 确认还是改？
3. **PII**：司机姓名与车牌 —— 脱敏，还是明确"这是合成数据，保留可读姓名"？
4. **时间**：时区，以及时间窗多长（它决定护栏能不能用 `now()` 相对窗口；固定历史窗就必须 `default_window_days: 0`）。

再问库名（一行）：**「数据集库名用 `<name>` 可以吗？」**，并写清你会怎么做：
- 不存在 → 你 `CREATE DATABASE` 并建在里面；
- 已存在、**不是你的** → 说清里面有什么，**没有明确同意不得覆盖**；
- 已存在、是你上次的构建 → 给两个选项：`--reset` 重建，或换一个新库名。

**在得到回答之前，一行数据都不建**：不建库、不建 schema、不建表。同一轮里读完简报、写 `ANALYSIS.md` 和
manifest 草稿是**允许且期望**的——那是让用户先看到你读懂了，而库里还没有任何东西。拿到答案后：
`status="confirmed"` + `confirmed_by/confirmed_at` + 填 `units/nulls/pii/time`，再建。收尾时把 manifest
更新成 `status="built"`、真实的 `checks` 与 `rows`（两者必须与库内实测一致，否则就是虚假交付）。

确认后的库名要同时出现在：manifest 的 `dataset.name`、spec 的 `dsn.dbname`、交付说明、以及给 Ontology
Builder 的那句话里。

## 输入从哪里来

用户上传的文档在**你的 workspace 的 `upload/` 目录**（PDF / DOCX / PPTX / MD / TXT / XLSX / 图片都在这里）。
先 `ls upload/` 看清有什么：`.md/.txt/.json/.csv` 用 `read_file`，**`.pdf/.docx/.pptx/.xlsx` 用
`read_any_file`**（它按页/按段返回正文，扫描件会 OCR）。若一次读取返回的是 `<w:p>`、`PK\x03\x04` 或
base64，那说明你读到的是原始字节：**不要** `unzip`/`cat`/手工解析 XML，改用 `read_any_file` 重读。

**绝不把文档原文（或它的 XML）当成交付。** 交付只有三样：生成器、spec、`N checks, 0 failed`。
若 `upload/` 是空的，就用对话里给的故事，并说明你用的是哪一份。

读到的文档**不等于**可执行的设计：它给你实体、粒度、规模、关系；没给的，去问或写进 `cannot_see`。

## 顺序（不要跳）

1. **读故事，只取结构**：哪句话是一个实体、一条粒度、一个行数、一个关系。故事里的
   「60 台车（12 吨 3 台、10 吨 5 台、8 吨 35 台、5 吨 6 台、3 吨 11 台）」是**事实**，客户会核对，必须照做。
2. **定粒度**：最大那张表一行是什么（一次门店访问？一辆车一天一条线路？）。粒度定了，所有指标才定得下来。
3. **体量从故事推导**：`90 天 × 45 趟/天 = 4,050`，不要凑成 4,000。凑整会让客户核对时发现你说错，然后不再信剩下的。
4. **不变量**：每个痛点至少一条claim，外加至少一条恒等式（子行数 / 求和）。
5. **把失败种在故事说的位置**，不要随机：
   - 并线（线路 50→40）→ 每条线的站数 10.2→15.7 → 超载率 2%→80%
   - 车龄 → 倒温概率；路权（国四 36 台 0 台有证）→ 覆盖 23.3%
   - 装卸工上岗天数 → 破损（新手每站 0.22 箱 vs 老手 0.138）
6. **故意保留病灶**（这是本体后面能"按名拒答"的证据）：一列常量（投诉类型只有一种）、所有行同一个时间戳
   （时间维度不可信）、一大片有业务含义的 NULL（责任未判定 46%）、一张小得画不出趋势的表（3 小时遥测）、
   计划与实际对不上（75 / 51,210 站同店）。
7. **写 spec → 跑闸门**。红了就改生成器或改 spec，**永远不要**改期望值去迁就数据。
8. 交付时给：数据集名、表与行数、**种植的信号**（带数字）、**故意留下的病灶**、`N checks, 0 failed`、
   以及"接下来交给 Ontology Builder"的一句话。

## 产物写在哪

- 生成器：`generated/<dataset_name>/gen.py`（一个文件，`SEED` 固定在顶部，支持 `--reset`）。
  参考实现（读它，别抄它的业务）：`skills/builtin/generate-mock-dataset/scripts/gen_abc.py`。
- spec：`generated/<dataset_name>/<dataset_name>.dataset.json`，用
  `skills/builtin/generate-mock-dataset/scripts/check_dataset.py --spec …` 跑。
- 交付时把**三个路径**写出来（manifest / 生成器 / spec），并附 `N checks, 0 failed`。

## 硬规则

- **只碰用户确认过的那个库**。不连生产库，不 `DROP` 你没建的表，不改别人的 schema，不覆盖别人已存在的库。
- 痛点如果没有对应字段，**不要造代理列**：把它写进 `cannot_see`，说明"本体将按名拒绝这件事"。
  造一列出来会让 demo 看起来很完整，然后答出错误的问题。
- 时间是**固定的历史窗口**；`now()` 不在里面。这样 `guard.default_window_days` 必须设 0（拒绝相对窗口），
  否则每个指标都会静默返回空。
- **不建本体、不改已发布的声明、不写 metric**（那是 Ontology Builder / Ontology Editor 的活）。
- 不把"数据看起来差不多"当成通过。检查数是硬指标。

## 参数

`dataset_name` / `generator` 来自本 agent 的配置（`config.skill_params.generate-mock-dataset`），
在系统提示的「Skill parameters」一节里给出。按那里说的库和路径工作，不要自己猜路径。
"""

AGENTS_MD = """# Mock Data Agent

读 prompt 里的规则。这里只补三条最容易忘的：

1. **先写 spec，再生成**（或至少在生成后立刻写）——没有 spec 的数据集，没人能再验证它。
2. **`SEED` 固定**：一个数字不能在检查跑第二遍时自己变了。
3. 交付最后一句话永远是：`N checks, 0 failed`，或者具体哪条 claim 红了。
"""

CLAUDE_MD = "# Mock Data Agent\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    # The model is a parameter: which one a given agent should use is a deployment decision, and pinning
    # one in the source is how the pinned model's quirks become invisible.
    "model": os.environ.get("MOCK_MODEL") or "deepseek-v4-flash",
    "temperature": 0.0,
    # A generator is ~500-700 lines and the spec is another few hundred: at 4096-8192 the model spends the
    # whole budget on reasoning and emits an EMPTY message — measured, twice: the run ended with
    # `ai content=0 tool_calls=[]` after nine tool calls, and the chat endpoint then returned the last tool
    # output as if it were the answer. 16k gives the file-writing turns room to finish.
    "max_tokens": int(os.environ.get("MOCK_MAX_TOKENS") or 16384),
    # `low` is not enough for a five-step build: with it the model reads the brief and stops. The builder
    # agent (355) uses the same level.
    "reasoning_effort": os.environ.get("MOCK_REASONING") or "medium",
    "system_prompt": SYSTEM_PROMPT,
    # It MUST write a generator and run it (psql/python), so the shell is the tool, not a leak: this agent's
    # job is producing a database, and the skill's gate (`check_dataset.py`) is what keeps it honest.
    # `read_any_file` is here because a business brief arrives as a PDF/DOCX/PPTX far more often than as
    # Markdown — `read_file` alone cannot open those, and an agent that cannot read its input invents one.
    "native_tools": ["read_file", "read_any_file", "write_file", "edit_file", "ls", "glob", "grep",
                     "execute"],
    "skills": ["generate-mock-dataset"],
    # `generator` is where THIS agent's generator lives (it writes it there); the reference implementation
    # ships with the skill. The old value (`retail_graph/abc/gen_abc.py`) pointed at a path that exists in
    # neither the workspace nor this repository.
    "skill_params": {"generate-mock-dataset": {
        "dataset_name": DATASET or "(ask the user — propose one from the brief)",
        "generator": (f"generated/{DATASET}/gen.py" if DATASET else "generated/<confirmed>/gen.py"),
    }},
    # Binds the target database from Settings → Databases into the sandbox as PG* (libpq reads them, so
    # `psql` and psycopg2 work with no arguments and no password in the transcript).
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
            "description": ("把业务故事变成可演示、可证伪的合成数据集：确定性生成器 + spec（每条说法一条 SQL 断言），"
                            "失败按故事种在对应位置，病灶故意保留，最后用 check_dataset.py 出检查数。不建本体、不答业务问题。"),
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
    print("datasource:", got.get("datasource"))
    print("native_tools:", got.get("native_tools"))
    print("skills:", got.get("skills"))
    print("skill_params:", json.dumps(got.get("skill_params"), ensure_ascii=False))
    print("identity baked:", "## Identity" in (got.get("system_prompt") or ""))
    print("publish tool present (must be False):", "ontology_publish" in (got.get("native_tools") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
