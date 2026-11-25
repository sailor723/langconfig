# 数据库工具盘点与整理（2026-11-25）

范围：`custom_tools` 里 category=`database` / `data`，以及以 `db_` / `pg_` / `sql` / `sqlite` 命名的行（共 30 行）。
目的：在加新工具之前先看清已有的，避免第三套「查库」入口；并明确**哪些必须保留**（LangGraph 编译图查询工具）。

## 1. 全量清单（按能力分类）

### A. 写结构（DDL）

| 工具 | 写什么 | 目标库 | 两段式 | 绑在 |
|---|---|---|---|---|
| `db_execute` | CREATE/ALTER/DROP/TRUNCATE/COMMENT（单语句） | **任意库**（除平台库/template/postgres） | ✅ plan→confirm | 394 |
| `db_rename_column` | 改列名 | 任意库 | ✅ | 375 / 394 |
| `db_review(apply=true)` | 建主键/外键 | 任意库 | ✅ | 375 / 377 / 393·tables / 394 |
| `db_build_from_file` | CREATE DATABASE + CREATE TABLE + 灌数 | 新库 | ✅ | 375 / 393·tables |
| `sqlite_load_csv` | SQLite 建表 | SQLite 文件 | — | 115 / 159 / 165 / 329 |

### B. 写数据（DML / UPDATE）

| 工具 | 写什么 | 目标库 | 守卫 | 绑在 |
|---|---|---|---|---|
| `db_execute` | INSERT/UPDATE/DELETE（单语句） | 任意库（同上） | 单语句、拒绝服务器级动词、拒绝平台库 | 394 |
| `pg_execute` | INSERT/UPDATE/DELETE | **仅平台库** | 只允许三种 DML、禁 `;` 堆叠 | 无 |

> 两者是**互补而非重复**：`db_execute` 管「别的库」，`pg_execute` 管「平台库的行级 DML」。平台库的 DDL 两边都拒绝 —— 那要人在 psql 做。

### C. 查询（只读 SQL）

| 工具 | 目标 | 特点 | 绑在 |
|---|---|---|---|
| `db_query` | **任意库**，按 `db_name` | 批量 `sqls=[…]`，一条连接一次往返 | 375 / 377 / 393·metrics / 393·modeller / 393·tables / 394 |
| `pg_query` | 平台库 | 老入口，与 `db_query(db_name=平台库)` 等价 | 115 / 159 / 165 / 281 |
| `sqlite_execute` | SQLite 文件 | 只读 SQL | 115 / 159 / 165 / 329 / 343 |
| `databricks_query` | 外部 Databricks warehouse | 只读 | 无 |

### D. 元数据 / 发现（catalog）

| 工具 | 作用 | 范围 | 绑在 |
|---|---|---|---|
| `db_list_databases` | 服务器上所有库：大小、对象数、平台/模板标记、可写性 | 服务器级 | 394 |
| `db_describe` | 任意库的表清单（带行数估算）；某表的列/索引/约束/精确行数 | 任意库 | 394 |
| `pg_list_tables` | 表 + 行数 | **仅平台库** | 115 / 159 / 165 |
| `pg_describe_table` | 列详情 | **仅平台库** | 115 / 159 / 165 |
| `pg_list_agents` / `pg_get_agent` / `pg_list_projects` / `pg_list_documents` / `pg_list_skills` / `pg_list_custom_tools` | 平台自身的元数据（不是业务库） | 平台库 | 1 / 115 / 159 / 165 |

### E. 校验 / 对账（读，但为「证明」服务）

| 工具 | 作用 | 绑在 |
|---|---|---|
| `db_plan_from_file` | Excel/CSV → 建库方案（不建库） | 375 / 393·tables |
| `db_verify_against_file` | 文件 vs 库：行数、列、逐值、合计 | 375 / 393·tables |
| `db_review` | 体检：行数/空值/主键外键候选 | 375 / 377 / 393·tables / 394 |

### F. LangGraph 编译图查询（**保留，不动**）

| 工具 | 背后 | 为什么保留 |
|---|---|---|
| `sql_agent_tool` | `langgraph/sql_agent.py` → `run_sql_agent()` | 步骤固定（发现表 → 读 schema → 生成 SQL → 自检 → 只读执行 → 解释），**可控且可复现**；比让模型自由拼 SQL 稳 |
| `advanced_sql_agent_tool` | 同上（多步规划版） | 复杂问题用；未绑定到任何 public agent，保留待用 |
| `neo4j_agent_tool` / `neo4j_agent_advanced_tool` | `langgraph/neo4j_agent*.py` | 图库查询的编译图入口，同理保留 |

**结论（与你的判断一致）**：自然语言问库走 LangGraph 工具；精确 SQL 走 `db_query`；两者不是替代关系，是「谁决定 SQL」的区别 —— 编译图里 SQL 由**固定的步骤**产出，`db_query` 里 SQL 由**当次模型**产出。后者灵活、前者可审。

### G. 生成物（不是查询，但常被归进来）

`db_dashboard`（交互式 HTML 看板，两段式）、`python_execute`（通用代码执行，非数据库专用）。

## 2. 发现的问题

1. **`usage_count` 是死的。** 88 个工具全部为 0，包括我们刚刚真实调用过的 `db_list_databases`。写入点在
   `core/agents/tool_loader.py:502`（加载时 +1），说明聊天路径的加载**没走到那里**（或走了另一条缓存路径）。
   后果：无法用数据回答「哪个工具真被用过」，整理只能靠绑定关系推断。
2. **`db_query` 的描述指错门。** 它写着「DDL/DML（建视图、改表）用 `execute`」—— 那是 deep agent 的沙箱工具，
   plain agent 没有；应该指向 `db_execute`。这种描述会让 agent 去找一个不存在的工具。
3. **两套「查平台库」入口并存**：`pg_*`（老）与 `db_*`（新，能查任意库）。功能上前者是后者的子集。
4. **未绑定的工具**：`pg_execute`、`advanced_sql_agent_tool`、`databricks_query`、`neo4j_*`、`pg_list_documents`、
   `pg_list_skills`（其中有些是刻意留作能力储备，需要标注清楚）。
5. **`db_execute` 与 `pg_execute` 的边界只写在描述里**，没有一份对照表；新写 agent 的人容易两个都挂上。

## 3. 整理建议（按风险排序）

| # | 动作 | 风险 | 影响 |
|---|---|---|---|
| 1 | 修 `db_query` 描述里的 `execute` → `db_execute`；并在 `db_execute`/`pg_execute` 描述里互相点名边界 | 无 | 少一次「找不到工具」 |
| 2 | 修 `usage_count`：在聊天路径的工具加载处也计数（或明确指出哪条路径不计数）；先补一个最小验证 | 低 | 以后整理有数据支撑 |
| 3 | 给 `pg_*` 打 `is_public=false`（保留行、保留绑定给老 agent） | 低 | 工具列表少 8 个重复入口；老 agent 不受影响 |
| 4 | 给未绑定且非储备用途的工具（`pg_execute` 保留给平台库维护，标注）加 `note`/标签，说明「保留原因」 | 无 | 下一次盘点不用重新判断 |
| 5 | 写一份「DB 工具选择表」进 `docs`：问库规模 → `db_list_databases`；看结构 → `db_describe`；精确查 → `db_query`；NL 问 → `sql_agent_tool`；写一条 → `db_execute`；平台库行级改 → `pg_execute`；对账 → `db_verify_against_file` | 无 | 新 agent 不再乱挂工具 |

## 4. 整理已执行（2026-11-25）

| 动作 | 结果 |
|---|---|
| `db_query` 描述指错门（`execute` → 深 agent 才有的沙箱工具） | 改为指名 `db_execute`（任意库、两段式）与 `pg_execute`（平台库行级 DML），并补「看结构用 db_describe」 |
| `pg_execute` 描述 | 补「别的库用 `db_execute`；两个写工具都不做 DDL」——两个写入口互相点名，避免重复实现守卫 |
| 工具「退休」机制 | `custom_tools` 加 `is_deprecated` / `superseded_by` / `deprecated_reason`（迁移 `041_tool_retirement`）；`/api/tools/registry` 默认不返回废弃项，`?include_deprecated=true` 才给（含「→ 用哪个替代」） |
| 严格子集退休 | `pg_query → db_query`、`pg_list_tables → db_describe`、`pg_describe_table → db_describe` |
| 平台自省换分类 | `pg_list_agents / get_agent / projects / documents / skills / custom_tools` → 分类 `platform`（查的是平台状态，不是业务库） |
| 休眠能力标注 | `advanced_sql_agent_tool`、`databricks_query` 标废弃 + 写明「未启用」原因（没有替代品，是**没开**而不是**换掉**） |
| 门禁 | `tests/test_tool_registry_deprecation.py`：废弃项不进候选、`include_deprecated=true` 才出、每条废弃都要有理由、subset 必须指名接任者且接任者自己可得 |

整理后：`/api/tools/registry` **94 → 89**（隐藏 5 个），数据库相关候选从 24 收敛到 **13** +
6 个平台自省（新分类）。

### 仍然 OPEN

1. **`usage_count` 仍然不动**（88 行全 0，包括刚真实调用过的 `db_list_databases`）。写入点在
   `core/agents/tool_loader.py:502`（加载时 +1）——说明聊天路径没走到那里。修之前，任何「哪个工具真被用过」
   的结论都只能靠绑定关系推断。
2. **`sqlite_*`** 两个仍在候选里（4 个 public demo agent 绑着）。我们的栈是 Postgres，SQLite 是遗留演示路径；
   要么把 demo 迁到 Postgres，要么同样标废弃。
3. **`db_dashboard`** 与本体看板（`dashboard.json` + 工作台）是两条生成路径，迟早给出两块不一样的板。留着但
   没有第二个消费者，建议下一步明确它是否退役。
