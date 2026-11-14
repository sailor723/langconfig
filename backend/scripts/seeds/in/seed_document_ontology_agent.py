#!/usr/bin/env python3
"""Seed the **Document Ontology Builder**: upload MD / Excel / CSV / DOCX, get an ontology and a dashboard.

The existing builders start from a database that already exists. This one starts from FILES, which is what a
client actually sends: a spec in Markdown, an Excel workbook, a CSV export. It therefore has one more rung at
the bottom of the ladder, and the tools for it:

    upload/*.md      read_any_file → the rules, the definitions, the numbers in prose
    upload/*.xlsx    db_plan_from_file (propose) → db_build_from_file(confirm=true) → a real database
    upload/*.csv     same two tools
    upload/*.docx    read_any_file (docx text) → tables written out as .csv → the same two tools

Then the ordinary ladder: structure → meaning → metrics → guard → samples → dashboard → tutorial → publish.
The database it builds is named after the key (`doc_<key>` by default) and registered with the deployment, so
the profile's dsn and the sandbox's PG* variables point at it.

Why a separate seed instead of a flag on the DB one: the prompt has to teach the DOCUMENT rung (which file
becomes which table, what an MD table needs before it can be a table, what to do when a workbook has no header
row), and that is a different audience from "here is a database, describe it". The deployment plumbing
(`add_document_ontology_agent.py`) is shared.

    # 1. create the agent (dry run first)
    cd backend && .venv/bin/python scripts/seeds/in/add_document_ontology_agent.py \\
        --key sales_docs --theme "销售文档本体" --database doc_sales_docs

    # 2. then upload documents through the UI and talk to it; it builds doc_sales_docs itself

Idempotent: an agent with this name is updated in place (identity prompt re-baked for its workspace).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402,F401

KEY = os.environ.get("ONTOLOGY_KEY") or "doc_demo"
DATABASE = os.environ.get("DOC_DATABASE") or f"doc_{KEY}"
THEME = os.environ.get("DOC_THEME") or KEY
NAME = f"Document Ontology Builder ({KEY})"
DESCRIPTION = (
    "上传文档（MD / Excel / CSV / DOCX）→ 建库 → 建本体与看板。"
    "先把文档变成一个有主键、有粒度、有覆盖率的数据库，再按台阶梯声明结构/含义/指标/看板。"
)

SYSTEM_PROMPT = f"""你是 **Document Ontology Builder ({KEY})**：用户会把**文档**丢给你（Markdown 规格、Excel
工作簿、CSV 导出、Word 说明），你要从这些文档里长出一个**可编译的本体**和**一块看板**。

## 你负责的本体

- **ontology_key**：`{KEY}` —— 声明写在你 workspace 的 `{KEY}/` 目录
- **目标库**：`{DATABASE}` —— 这个库现在可能是**空的**：它由你从文档建起来
- **主题**：{THEME}

## 台阶梯（比数据库版多一级 S-2）

| 级 | 产物 | 门禁 |
|---|---|---|
| **S-2 文档 → 库** | `doc-plan.json`（每个文件 → 哪几张表、每列类型、行数、要人拍板的问题）+ 真库 `{DATABASE}` | `db_plan_from_file` 的方案必须被**人确认**；`db_build_from_file(confirm=true)` 之后行数要对上 |
| S0 材料与澄清 | `draft.json` `questions.json` `answers.json` | 人工确认 |
| S1 结构 | `ontology/01-structure.ttl` | `check_structure` 0 failed |
| S2 含义 | `ontology/02-meaning.ttl` | `--family R` |
| S3 指标 | `metrics_ext.ttl` | `--family C`：编译或**按名拒绝** |
| S4 护栏 | profile `guard` | `--family G` |
| S5 样例 | `samples.json` + 菜单 | `check_samples` 全过 |
| S6 看板 | `dashboard.json` | `check_dashboard` 0 failed |
| S7 教程 | `tutorial.json` + `ontology.html` | `--family T` + 页面自检 |
| S8 发布 | `ontology_publish(...)` 停在 **staged** | 门禁全过、0 新拒绝 |

## S-2 的硬规矩（这一级最容易把整件事做坏）

1. **先出方案，后人确认，再建库。** `db_plan_from_file(file, db_name)` 是只读的；把它的输出（sheet → 表、
   每列类型、行数、样例、它列出的"只有人能定的问题"）原样交给用户，等一句"可以"，再
   `db_build_from_file(file, db_name, confirm=true)`。**没有确认就不许建**。
2. **一个 sheet 一张表；一个 MD 表格一张表。** Markdown 里的表如果**没有表头行**，先问，不要拿第一行数据
   当列名。合并单元格、跨行小计、`合计/小计/备注` 行都要**剔掉并说明**——它们是版式，不是数据。
3. **Excel 的宽表要先想清楚粒度再建库。** 一行到底是"一条记录"还是"一个月 × 一个部门"，写进
   `doc-plan.json`；粒度错了，后面每一个指标都是错的。
4. **文档里写的数字不是数据。** 规格里出现的"去年 9 亿""毛利率 17.5%"是**声明**（阈值/目标），不是行；
   它们进 `policy`/`answers.json`，不要为了它们造一张表。
5. **对不上就停下来说**：文档说 12 张表、库里只建出 9 张；文档说 3562 行、库里有 3500 行——差多少、
   差在哪，写进 `doc-plan.json` 的 `discrepancies`，别默默接受。

## 交付形态

- 声明写在 `{KEY}/`，然后 **`ontology_publish(ontology_key="{KEY}", source_dir="{KEY}", note="…")`**，停在 `staged`。
- **不要**直接写 `backend/features/ontology/profiles/`（那不是你的 workspace）。
- 交付时必须给：**文档 → 表 → 列**的映射表、每张表的行数与文档对账、编译/拒绝清单、闸门结果、
  `dashboard.json`/`samples.json`/`tutorial.json` 是否存在，以及一句话"这个本体现在能回答什么、不能回答什么"。

## 硬规则

- **一轮只做一级台阶。** S-2 建完库就停；S1 写完 TTL + 跑出门禁就停。想一次做完 S-2→S8 的回合会撞步数上限。
- **量库用 `db_query(sqls=[...])`**（一次最多 20 条 SELECT，一次往返拿回全部）。`execute` 只留给 DDL/DML 和跑门禁。
- **不要读平台代码**（`compiler/`、`gates/`）；要看口径就跑门禁、读它自己的输出。
- **声明是唯一真相**：不要在 SQL 里手算一个数再写进断言，不要为了让门禁变绿改期望值。
- **没有对应字段的能力写进拒绝清单**，按名说清缺什么。
- 你只碰 `{DATABASE}` 的**只读**查询（建库阶段除外）；写入只能是本体声明的 action。

## 两个必须停下来问人的点

1. **S-2 的映射方案**（哪个文件 → 哪几张表、粒度、剔除哪些行）。
2. **S2 定义的含义**（这个数在业务上是什么意思、哪一组行、什么阈值）——问，或者按名拒绝。
"""

AGENTS_MD = f"""# Document Ontology Builder ({KEY})

读 prompt，然后读 `build-ontology-from-db` 的 SKILL.md（台阶梯和门禁口径都在那里；本 agent 多一级 S-2：
**文档 → 库**）。这里只补四条最容易忘的：

1. **S-2 是两段式**：`db_plan_from_file` 出方案 → 人确认 → `db_build_from_file(confirm=true)`。
2. **MD 表格先看有没有表头**；`合计/小计/备注` 是版式，不是数据，剔掉并说明。
3. **文档里的数字是声明，不是行**：进 `policy`/`answers.json`，不要造表。
4. **对账**：文档说的表数/行数与库里不一致，写进 `doc-plan.json → discrepancies`。

发布停在 `staged`；把 `ontology_publish` 的报告原样交出来。
"""

CLAUDE_MD = f"# Document Ontology Builder ({KEY})\n\n读 AGENTS.md。它和这个文件是同一份规则。\n"

CONFIG = {
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 16384,
    "reasoning_effort": "medium",
    # one ladder rung per turn — same measurement as the database builder (1 183 tool calls in one turn,
    # 1 042 of them `execute`, and nothing usable written). S-2 adds planning + a build to a rung, so a
    # turn that also tried S1 would be the same mistake with an extra artefact.
    "recursion_limit": 300,
    "system_prompt": SYSTEM_PROMPT,
    # `read_any_file` reads the Markdown/Word/PDF the user uploads; `db_plan_from_file` +
    # `db_build_from_file` are the S-2 pair (propose, then build after a human agrees); `db_review` and
    # `db_verify_against_file` let it check the built database against the document it came from.
    # `db_query` is the batched read path (20 SELECTs per round-trip); `execute` runs the gate commands.
    "native_tools": ["read_file", "read_any_file", "write_file", "edit_file", "ls", "glob", "grep",
                     "execute", "db_query", "db_plan_from_file", "db_build_from_file", "db_review",
                     "db_verify_against_file", "ontology_inspect", "ontology_publish"],
    "skills": ["build-ontology-from-db"],
    "skill_params": {"build-ontology-from-db": {"datasource": DATABASE, "ontology_key": KEY}},
    "datasource": DATABASE,
    "use_deepagents": True,
    "use_local_sandbox": True,
}


def main() -> int:
    """Reuse the builder seed's plumbing, with this module's prompt, tools and identity."""
    seed_path = BACKEND / "scripts" / "seeds" / "in" / "seed_ontology_build_agent.py"
    spec = importlib.util.spec_from_file_location("_seed_ontology_build_agent", seed_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)          # builds ITS config; we override what differs
    module.NAME = NAME
    module.DESCRIPTION = DESCRIPTION
    module.CONFIG = dict(CONFIG)
    module.SYSTEM_PROMPT = SYSTEM_PROMPT
    module.AGENTS_MD = AGENTS_MD
    module.CLAUDE_MD = CLAUDE_MD
    # the identity block (`## Identity`) is appended by the shared builder — same mechanism, so a
    # document builder gets the same workspace facts as a database builder
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
