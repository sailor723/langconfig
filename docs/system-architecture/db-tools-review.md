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
| `db_execute` | INSERT/UPDATE/DELETE（单语句） | 任意库，**含平台库** | 单语句、拒绝服务器级动词、平台库只放行这三种 DML | 394 |
| ~~`pg_execute`~~ | — | — | **已退役**（`is_deprecated=true`，`superseded_by=db_execute`） | 无 |

> **写入口只有一个（2026-11-25 合并）。** 之前是两扇门：`db_execute` 按参数拒绝平台库，`pg_execute`
> 只服务平台库。两个问题让它站不住：① `pg_execute` **从未被任何 agent 绑定、从未被调用过一次**
> （`usage_count 0`、`last_used_at` 空、binders 0）；② 调用方得先知道"这个库是不是平台库"才能选工具——
> 而那个判断本来就该由守卫做，不该由工具身份表达。
>
> 现在规则写在动词 × 目标上：**平台库只放行 INSERT/UPDATE/DELETE；平台库的 DDL 一律拒绝**（那要人在 psql 做）。

### C. 查询（只读 SQL）

| 工具 | 目标 | 特点 | 绑在 |
|---|---|---|---|
| `db_query_agent` | **任意库**，按 `db_name` | 批量 `sqls=[…]`，一条连接一次往返 | 375 / 377 / 393·metrics / 393·modeller / 393·tables / 394 |
| `pg_query` | 平台库 | 老入口，与 `db_query_agent(db_name=平台库)` 等价 | 115 / 159 / 165 / 281 |
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
| `db_query_langgraph` | `langgraph/sql_agent.py` → `run_sql_agent()` | 步骤固定（发现表 → 读 schema → 生成 SQL → 自检 → 只读执行 → 解释），**可控且可复现**；比让模型自由拼 SQL 稳 |
| `advanced_db_query_langgraph` | 同上（多步规划版） | 复杂问题用；未绑定到任何 public agent，保留待用 |
| `neo4j_agent_tool` / `neo4j_agent_advanced_tool` | `langgraph/neo4j_agent*.py` | 图库查询的编译图入口，同理保留 |

**结论（与你的判断一致）**：自然语言问库走 LangGraph 工具；精确 SQL 走 `db_query_agent`；两者不是替代关系，是「谁决定 SQL」的区别 —— 编译图里 SQL 由**固定的步骤**产出，`db_query_agent` 里 SQL 由**当次模型**产出。后者灵活、前者可审。

### G. 生成物（不是查询，但常被归进来）

`db_dashboard`（交互式 HTML 看板，两段式）、`python_execute`（通用代码执行，非数据库专用）。

## 2. 发现的问题

1. **`usage_count` 是死的。** 88 个工具全部为 0，包括我们刚刚真实调用过的 `db_list_databases`。写入点在
   `core/agents/tool_loader.py:502`（加载时 +1），说明聊天路径的加载**没走到那里**（或走了另一条缓存路径）。
   后果：无法用数据回答「哪个工具真被用过」，整理只能靠绑定关系推断。
2. **`db_query_agent` 的描述指错门。** 它写着「DDL/DML（建视图、改表）用 `execute`」—— 那是 deep agent 的沙箱工具，
   plain agent 没有；应该指向 `db_execute`。这种描述会让 agent 去找一个不存在的工具。
3. **两套「查平台库」入口并存**：`pg_*`（老）与 `db_*`（新，能查任意库）。功能上前者是后者的子集。
4. **未绑定的工具**：`pg_execute`、`advanced_db_query_langgraph`、`databricks_query`、`neo4j_*`、`pg_list_documents`、
   `pg_list_skills`（其中有些是刻意留作能力储备，需要标注清楚）。
5. **`db_execute` 与 `pg_execute` 的边界只写在描述里**，没有一份对照表；新写 agent 的人容易两个都挂上。

## 3. 整理建议（按风险排序）

| # | 动作 | 风险 | 影响 |
|---|---|---|---|
| 1 | 修 `db_query_agent` 描述里的 `execute` → `db_execute`；并在 `db_execute`/`pg_execute` 描述里互相点名边界 | 无 | 少一次「找不到工具」 |
| 2 | 修 `usage_count`：在聊天路径的工具加载处也计数（或明确指出哪条路径不计数）；先补一个最小验证 | 低 | 以后整理有数据支撑 |
| 3 | 给 `pg_*` 打 `is_public=false`（保留行、保留绑定给老 agent） | 低 | 工具列表少 8 个重复入口；老 agent 不受影响 |
| 4 | 给未绑定且非储备用途的工具（`pg_execute` 保留给平台库维护，标注）加 `note`/标签，说明「保留原因」 | 无 | 下一次盘点不用重新判断 |
| 5 | 写一份「DB 工具选择表」进 `docs`：问库规模 → `db_list_databases`；看结构 → `db_describe`；精确查 → `db_query_agent`；NL 问 → `db_query_langgraph`；写一条 → `db_execute`；平台库行级改 → `pg_execute`；对账 → `db_verify_against_file` | 无 | 新 agent 不再乱挂工具 |

## 4. 整理已执行（2026-11-25）

| 动作 | 结果 |
|---|---|
| `db_query_agent` 描述指错门（`execute` → 深 agent 才有的沙箱工具） | 改为指名 `db_execute`（任意库、两段式）与 `pg_execute`（平台库行级 DML），并补「看结构用 db_describe」 |
| `pg_execute` 描述 | 补「别的库用 `db_execute`；两个写工具都不做 DDL」——两个写入口互相点名，避免重复实现守卫 |
| 工具「退休」机制 | `custom_tools` 加 `is_deprecated` / `superseded_by` / `deprecated_reason`（迁移 `041_tool_retirement`）；`/api/tools/registry` 默认不返回废弃项，`?include_deprecated=true` 才给（含「→ 用哪个替代」） |
| 严格子集退休 | `pg_query → db_query_agent`、`pg_list_tables → db_describe`、`pg_describe_table → db_describe` |
| 平台自省换分类 | `pg_list_agents / get_agent / projects / documents / skills / custom_tools` → 分类 `platform`（查的是平台状态，不是业务库） |
| 休眠能力标注 | `advanced_db_query_langgraph`、`databricks_query` 标废弃 + 写明「未启用」原因（没有替代品，是**没开**而不是**换掉**） |
| 门禁 | `tests/test_tool_registry_deprecation.py`：废弃项不进候选、`include_deprecated=true` 才出、每条废弃都要有理由、subset 必须指名接任者且接任者自己可得 |

整理后：`/api/tools/registry` **94 → 89**（隐藏 5 个），数据库相关候选从 24 收敛到 **13** +
6 个平台自省（新分类）。

### `usage_count` 已修（2026-11-25）

**根因不是「聊天路径绕过计数」，而是计数写错了地方。** 唯一的写入点在
`core/agents/tool_loader.py::load_custom` —— 那是**用户自定义工具**的加载路径；builtin/原生工具
（整个 `db_*`、`pg_*`、技能、文件系统族）走的是 `_load_builtin_from_db`，**从来没有加过 1**。所以 88 行全 0，
`last_used_at` 全空。

而且「加载时计数」本身就是错的数：它回答的是「这个 agent 被建成时带了哪些工具」，不是「有没有人真的调过它」。
整理要看的是后者。

**改法**：计数挪到**调用**处 —— `core/tools/usage.py` 包住工具的可调用体，`ToolFactory.create_tool` 在返回前
统一套上（两条加载路径都经过它，所以一次改动覆盖全部）。`load_custom` 里那行加载时 +1 已删除，避免一次调用被记成
两次、一次重建被记成一次使用。

三条规矩（都有门禁 `tests/test_tool_usage_counting.py`，5 条）：
① 计数失败绝不影响工具调用（无库、无行、会话已关 → debug 日志 + 吞掉）；
② **调用抛异常也计数，记成 `error_count`**，且异常照常抛给调用方（跳过它等于把失败藏起来）；
③ 重复包装不重复计数（agent 重建不该看起来像一次使用）。

实测（真回合）：`db_describe` 从 0 → 2，`last_used_at` 有时间戳；`db_list_databases` 那一轮没被调用，仍是 0 ——
这正是「能回答哪个工具真被用过」的样子。

### 写入口合并（2026-11-25）

| 变化 | 证据 |
|---|---|
| `db_execute` 接受平台库（仅行级 DML） | 实测：`insert/update/delete` 在 `langconfig` 上 plan→confirm 均执行成功（`rows_affected` 1/1/1）；`create table` / `drop table` / `alter table` 在平台库上仍 `REFUSED`；业务库 `chinook` 上 DDL 仍放行（`create`/`drop` 均 OK） |
| `pg_execute` 退役 | `is_deprecated=true`、`superseded_by=db_execute`、理由写明"从未被绑定或调用"；行保留，老配置仍可用 |
| 门禁 | `tests/test_db_admin.py` **25 项**：平台库 DDL 拒绝（含 `create`/`alter`/`truncate`/`drop`）、平台库行级 DML 允许（plan 阶段即返回 `kind=dml`）、平台库非 DML 语句（`grant`/`vacuum`/`select`）仍拒绝 |
| 真实回合 | agent 394（DB Manager）：「往 `zz_write_probe` 插一行」→ `db_describe` 看结构 → `db_execute` 出计划并**停下等确认**；回「确认执行」→ 执行成功，表里确有 `2 | from-agent` |
| 未做（有意） | `DEFAULT_HITL_POLICY` **没有**加 `db_execute`：它自带 plan→confirm，再加中间件打断等于一次写问两遍。原来那一行写的是 `pg_execute`（没人用的工具），等于这个策略从未生效过 |

### 平台自省 vs 业务库：分类真的分开了（2026-11-25）

§4 之前写着"`pg_list_agents` 等改成 `platform` 分类"——**那是文档超前于实现**：seed 里它们的 `category`
仍是 `database`，库里也没有 `platform` 这个取值。这次补上了：

| 动作 | 结果 |
|---|---|
| 新增 `platform` 分类（`_DEFINITION_CATEGORY` + 前端 `TOOL_CATEGORY_LABELS`） | `pg_list_agents` / `pg_get_agent` / `pg_list_projects` / `pg_list_skills` / `search_skills` / `pg_list_documents` / `pg_list_custom_tools` 归位 |
| registry 分类分布 | 改动前 `database 16` → 现在 **`database 13` / `platform 6`**（`pg_list_skills` 退役，故 7 行里可见 6 个） |
| 为什么值得分 | 这 7 个读的是**平台自身的表**（agent 模板 / 项目 / 技能 / 文档 / 工具），跟"查哪个业务库"无关；混在 `database` 里，每个 agent 选工具都要在一半无关条目里挑 |

### 退役工具从配置里清掉了（2026-11-25）

退役机制保证"已退役的工具不进候选、旧配置还能跑"——但**没人去改旧配置**，于是 22 个 agent 手里一直躺着
3 件死工具（`pg_query` 21 个、`pg_list_tables` 20 个、`pg_describe_table` 20 个，调用数全 0）。这次做了数据迁移：

| 旧名 | 新名 | 迁移的 agent |
|---|---|---|
| `pg_query` | `db_query_agent` | 22 |
| `pg_list_tables` | `db_describe` | 20 |
| `pg_describe_table` | `db_describe` | 20 |
| `pg_list_skills` | `search_skills` | 2（1、124） |
| 合计 | — | **22 个 agent，去重后每个工具列表少 2–3 项** |

迁移按"保序去重"做：`pg_list_tables` 与 `pg_describe_table` 同时存在时只保留一个 `db_describe`，不会把同一个工具
塞两次。迁移后复查：**除 `db_dashboard`（375，待定）外，没有任何 agent 再绑已退役工具**。

### `search_skills` 与 `pg_list_skills` 合并（2026-11-25）

两者读同一张 `skills` 表、同样的字段、各绑 2 个 agent、真实调用都是 0——"列全部"和"按关键词找"是同一个问题的两种问法。
现在 `search_skills(query="")` **空查询即列表**（按使用次数降序、最多 50 条），`pg_list_skills` 标记退役并
`superseded_by=search_skills`。实测：空查询 → `## Skills (50 shown, most used first)`；`query="ontology"` →
`## Matching skills for 'ontology' (5 found)`。

### 两条生成看板的路：靠身份区分，不靠谁更"新"（2026-11-25，方案 B）

同一个库可以有两条出图路径，**都保留**，因为需求不同：

| | 本体路（S6） | SQL 路（`db_dashboard`） |
|---|---|---|
| 输入 | 已登记本体（`metrics` 单一定义 + `dashboard.json`） | 一个库名 |
| 产物 | **JSON 规范**，工作台渲染 | 自包含 HTML（D3 内联），落 `generated/` |
| 校验 | `check_dashboard` 四道门禁（结构/词汇/样例/真值 R2） | 页面合计 vs 重跑 cube 一次 |
| 适合 | 发布、被引用、跨报表一致 | 陌生库的一次性探索 |

风险不是"两份代码"，而是**同名 KPI 两个数字、两块板都像官方**。所以加了三条可检查的规则：

1. **身份**：页面的 `meta` 行固定带 `探索性（未治理）`，工具返回串以 `[探索性看板 · 未治理]` 开头。
2. **不占发布看板的位置**：目标库若已被某本体治理（profile 的 `dsn.dbname` 相同且有 `dashboard.json`），
   文件名从 `<db>_dashboard.html` 改成 **`<db>_explore.html`**，并在页面顶部横幅点名那份发布看板。
3. **同名拒绝**：度量名与已发布看板的 KPI id 归一化后相同 → **拒绝渲染**（`REFUSED` 并指名
   `profile:metric`），不重算一遍。

门禁：`tests/test_db_dashboard_identity.py`（4 项）。实测：`chinook`（未治理）→ 正常出图；
`store_monthly_xlsx`（本体 `store_monthly_v1` 治理中）→ 改名 `_explore.html` + 横幅点名；
`collides_with_governed('store_monthly_xlsx','returnRate')` → `['store_monthly_v1:returnRate']`。

#### 顺带修掉一个"从来没有跑过一次"的 bug

验证时 `db_dashboard` 直接抛 `TypeError: _pg_conn_kwargs() got multiple values for argument 'dbname'`。
根因：`services/db_dashboard._connect` 写的是 `_pg_conn_kwargs(host, port, user, password, dbname=db_name)`，
而该函数的签名是 `(host, port, user, dbname="", *, password="")` —— **password 是 keyword-only**，
按位置传就落到了 `dbname` 上，与 `dbname=db_name` 冲突。也就是说这个工具自诞生起**每一次调用都会抛异常**，
这也解释了它 `usage_count = 0`、`last_used_at` 为空：不是没人用，是从来不能用。已改为关键字传参。

### 全库体检：`usage_count = 0` 不等于"没人需要"（2026-11-25）

87 个工具里 **79 个从未被调用过**（`usage_count 0`、`error_count 0`、`last_used_at` 空）。按"是否坏了"分两批查：

| 检查 | 方法 | 结果 |
|---|---|---|
| 能否**加载** | 走 agent 真正的加载路径 `ToolLoader._load_builtin_from_db([id])` | 79/79 全部正常，0 失败 |
| 能否**调用** | 对数据库族逐个人工冒烟：只调读路径与 plan 阶段（`confirm=False` / `apply=False`），不写任何东西 | 发现 **3 个真 bug，全在 `services/db_dashboard.py`**，见下 |

三个 bug 的共同点是**都在"加载没问题、一调就炸"这一层**——所以"从未被调用"既是它们的症状，也是它们没被发现的原因：

1. `_connect` 把 `password` **按位置**传给 `_pg_conn_kwargs`（它是 keyword-only），落进了 `dbname` →
   `TypeError: got multiple values for argument 'dbname'`，**每次调用必炸**。
2. 修掉上一条后又把已解析的 `password` **反向喂回** `_pg_conn_kwargs`，触发它自己的守卫
   「a database password is not a tool argument」——内部管线撞上了面向 agent 的护栏。
3. `cube()` / `verify()` 调 `_connect(db_name)` 时**不带连接参数**，于是回落到 libpq 默认（:5432），
   报「database "chinook" does not exist」——明明几行之上连接已经解析对了。

修法：`_connect` 直接用已解析的 host/port/user/password 构造 psycopg2 参数（缺省交给 libpq 的 PG* 环境），
并把 `**conn` 贯穿 `cube()` / `verify()`。

冒烟结果（全部 ✓）：`db_query_agent`(读)、`db_dashboard(plan)`、`db_review(plan)`、
`db_rename_column(plan)`、`db_admin.list_databases` / `describe` / `execute(plan)`。
带真实文件参数的三个（`db_plan_from_file` / `db_build_from_file` / `db_verify_against_file`）
和 `talent_verify_jd_report` 未冒烟（需要一份真实 Excel/CSV 与 JD），已记录在案，不算通过。

**结论（可复用的规矩）**：`usage_count = 0` 且 `error_count = 0` 且 `last_used_at` 为空，
既可能是"没人需要"，也可能是"从来没成功过"。区分它们只能靠**真调一次**，不能靠读代码。

### 文件类 + async 工具也已冒烟（2026-11-25）

| 工具 | 输入 | 结果 |
|---|---|---|
| `db_plan_from_file` | 真实 CSV（3 行 4 列，放调用者工作区） | ✓ 出方案，**未建库** |
| `db_build_from_file` | 同上，`confirm=False` | ✓ 明确拒绝执行（"confirm=false — nothing was created"），库不存在 |
| `db_build_from_file` | 同上，`confirm=True` | ✓ 建库成功；独立核对 `rows=3 total=425` |
| `db_verify_against_file` | 同上 | ✓ 出核对报告 |
| `web_search` / `web_fetch` / `tavily_search`（async） | 真实查询 / URL | ✓ 三个都返回结果，无异常 |
| `create_skill`（async） | 故意传空参数 | ✓ 拒绝："description is required"（没落库） |
| `sync_skills`（async） | `dry_run=True` | ✓ 出 dry-run 报告，未写入 |

（`db_plan_from_file` 第一次用 `/tmp/…` 路径被拒——文件类工具只认调用者工作区，这是设计，不是 bug。）

### DDL 收敛成一条路（2026-11-25）

以前 DDL 有**四个入口、四套守卫**：`db_execute`（走 `db_admin`）、`db_rename_column`（自己 `cur.execute`）、
`db_review(apply=True)`（自己 `cur.execute`）、`db_build_from_file`（建库建表）。也就是说 `db_admin` 里那套
「单语句 / 服务器级动词 / 平台库 DDL 拒绝」的守卫，**只覆盖了四分之一**。

现在 `db_rename_column` 与 `db_review(apply=True)` 的每一条 `ALTER` 都走 `services/db_admin.execute(confirm=True)`。
实测：

| 场景 | 结果 |
|---|---|
| 业务库 `ddl_probe` 改名 | ✓ `public.t1.b → bee` 执行成功 |
| 业务库 `db_review(apply=True)` | ✓ `t1: PK (a) ok`，`pg_constraint` 里确有 `t1_pkey` |
| **平台库** `langconfig` 改名 | ✓ **REFUSED**（"DDL on the database this app runs on is not an agent's job"），实测列名仍是 `name` |
| 门禁 | `test_db_admin`(25) + `test_db_dashboard_identity`(4) + `test_tool_registry_deprecation` + `test_db_tools_confirm` = **52 passed** |

顺带修掉一个连锁问题：`db_review` 自己的 SELECT 开了隐式事务、持有 `ACCESS SHARE`，而 DDL 走第二条连接要
`ACCESS EXCLUSIVE` —— 于是**自己锁自己**，报 `canceling statement due to statement timeout`。修法是在应用约束前
`conn.rollback()` 结束读事务。

### 375 表格建库：它真的做了什么（2026-11-25 复查）

**它是什么**：`deepagents` agent，模型 `deepseek-v4-pro`，12 个工具（`list_files` / `read_any_file` / `glob` /
`db_plan_from_file` / `db_build_from_file` / `db_verify_against_file` / `db_review` / `db_query_agent` /
`db_rename_column` / `db_dashboard` / `write_file` / `skill`），3 个技能（`db-excel-to-postgres` 等）。

**它自己的历史（没有虚构，是库里会话 1966/1967）**：`skill(db-excel-to-postgres)` → `list_files` →
`db_plan_from_file` → `read_file` → `db_build_from_file`（`meeting_hub`，3562 行）→ `db_verify_against_file` →
`db_query`。顺序就是技能要求的顺序。

**我复跑了一遍（2 sheet 的真实 xlsx，含金额/布尔/日期/空列）**：

| 阶段 | 结果 |
|---|---|
| `db_plan_from_file` | 逐 sheet 列表、逐列推断类型、给样例，并主动列出"待确认点"（金额为什么是 NUMERIC、备注为什么一半为空）——**不建库** |
| `db_build_from_file(confirm=True)` | 建库建表灌数，`Row counts match the workbook.`，并写建库标记（可 `recreate=true` 重建） |
| `db_verify_against_file` | **PASS**：行数 4 vs 4、列数 6 vs 6、整行一致 4/4，并逐列对 sum（订单号 10 vs 10、金额 426.74 vs 426.74） |
| `db_review(apply=True)` | 报告里给 PK 候选，apply 后 `orders: PK (订单号) ok`，`pg_constraint` 里确有 `orders_pkey` |

**这次复查挖出的三个问题（都已修 + 加门禁）**：

1. **布尔被建成文本**：`已付款` 里是 `TRUE`/`FALSE` 文本时 → `TEXT`。`_infer_pg_type` 只在值是 Python `bool`
   时才给 `BOOLEAN`，而 CSV 导出/手填的表格基本都是文本。修：文本 `TRUE/FALSE` 也推断 `BOOLEAN`
   （Postgres 会把这些字面量转回布尔）。门禁 `tests/test_db_build_types.py`（5 项）。
2. **金额按中文列名不算金额**：money 正则只有 `amount|price|...`，`金额` 不在其中 → 整数值的金额列被建成 `BIGINT`。
   **实锤**：`store_monthly_xlsx.月度经营` 里 `营业额`、`退货额` 都是 **bigint**（`客单价` 因为有小数才是 numeric）。
   修：正则补中文（金额/单价/总价/价格/收入/营业额/销售额/成本/费用/税/折扣/工资/预算/余额/毛利/净利/客单价）。
3. **模型把批量放进 `sql` 会崩**：`db_query_agent(sql=[...])` 抛 `AttributeError: 'list' object has no attribute
   'startswith'`（schema 写的是 `sql: str`，但运行时参数不限类型）。修：列表入参按 `sqls` 批处理。

**还没解决的两个设计问题（留给决策）**：

- **375 的 `config.database` 是 `null`**：它的 `db_*` 工具因此全部以**平台自己的超级用户**身份连库。对一个"读任意
  上传文件 + 建库"的 agent，这是最宽的口子；而它本可以是某个只读/受限连接。
- **`db_dashboard` 仍绑在 375 上**（已退役）：按方案 B 它是"探索性"产物，但它出现在一个**建库**agent 的工具列表里，
  语义上更像该由分析类 agent 拥有。

### 仍然 OPEN

1. **`sqlite_execute` / `sqlite_load_csv`** —— 仍在候选里，**23 / 22 个 agent 绑着、真实调用 0**。栈是 Postgres，
   SQLite 是遗留演示路径；要么把 demo 迁 Postgres 后退役，要么现在标废弃（会从那些 agent 手里少两个死工具）。
   这是本次盘点唯一未收的重复项。
2. ~~`db_dashboard` 是否退役~~ —— **已收**：与本体看板重复，且每次调用必抛 `TypeError`；实现/seed/工具行全部删除、
   375 解绑，见 §4「两条生成看板的路」与 §8.5。
3. **375 的 `config.database` 是 `null`** —— 它的 `db_*` 工具因此以平台超级用户身份连库（见 §4 的 375 复查）。
   一个"读任意上传文件 + 建库"的 agent 用最宽的连接，值得改成一条明确连接。

## 5. 连接模型：全局配连接，agent 只选一个（2026-11-25）

**模型**（最小、和 VS Code 一致）：`Settings → Databases` 里配**连接**（名字 + host/port + 用户 + 密码，密码
Fernet 加密存储）；agent 的 Database 设置**只选一个连接名**。一条连接 = 一台服务器，**它下面的所有库都能查** ——
`db_query_agent` 只带库名，`db_list_databases` 列的就是这条连接的库。

### 之前断在哪（实测，2026-11-25）

`config.database` **只喂给 deep agent 的沙箱**（`execute` 里的 psql/脚本），而进程内工具
（`db_query_agent` / `db_review` / `db_describe` / `db_execute`）一律读 `os.environ` 的 `POSTGRES_*`。后果：

- 普通 agent 的 Database 设置**没人读**（`test_db` 就是这种：它的区块是装饰品）；
- 所有进程内 DB 工具都以**部署超级用户**身份运行，任何绑了 `db_query_agent` 的 agent 都能读平台库；
- 还有一层：内置工具的 `implementation_config.code` 是**seed 时嵌入的副本**，改 `tools/native_impl.py`
  不会影响正在运行的 `db_query_agent`，必须 `seed_builtin_tools.py --refresh` 重新生成行。

### 现在（已接通并验证）

| 环节 | 实现 |
|---|---|
| 连接清单 | `services/agent_database.list_connections()` / `default_connection_name()`（读 Settings → Databases，不返回密码） |
| agent 选一个 | `config.database = {mode:'catalog', name:'<连接名>'}`；空 = 用 Settings 里标 `default` 的连接（再没有就报错，不静默降级） |
| 运行时绑定 | `bind_run_db_env()`（contextvar，**按工具调用**绑定，仿 `sandbox_scope`；并发互不可见）+ `core/tools/db_scope.py` |
| 工具取连接 | `_pg_conn_kwargs` 先读运行期绑定（host/port/user/password），`db_name` 仍是工具参数 |
| 两条装配路径 | 普通 agent：`core/agents/factory/assembly.py`；deep agent：`services/deepagent_factory/support.py` |
| UI | 普通 agent 编辑器新增「数据库连接 / Database connection」单选框（写 `config.database`）；deep agent 原有的 Database 区块同源 |

**证据**（真回合，不是推断）：建了两个连接 `local-server`（部署角色 `langconfig`）与 `local-readonly`
（只读角色 `db_read`，`LOGIN` 无写权限）。

- `test_db`(395) 选 `local-readonly` → chat 里 `select current_user` 回答 **`db_read`**；
- 同一台机器上 `DB Manager`(394) 选 `local-server` → 回答 **`langconfig`**，并正确列出 19 个库。

也就是说：**一个 agent 的连接设置现在真的决定它用什么身份、连哪台服务器**，而不再是装饰。

### 遗留

1. `db_execute` 的写权限还应跟连接分级（`role: readonly|readwrite|admin`）—— 现在只靠「连接用只读角色」实现，
   schema 里还没有这个字段。
2 老连接条目（`kind: target` + `dbname`）语义是「这条连接的默认库」，保持不变；要在 UI 上区分「连接」与
   「某个库」还需要一轮重命名（`dbname` → 可选默认库的说明）。

## 6. 对外与否：按桶决定，不再有复选框（2026-11-25）

用户决定：**system → 永远不对外；business → 全部对外**。所以 Settings 页面上的勾选框全部删掉，
`/api/graph-studio/databases/catalog` 的 `offered` 列表改由 `bucket` 推导：

| 桶 | 是否进 SQL 选择器/分析页 | 依据 |
|---|---|---|
| `system`（`langconfig*`、`postgres`、`template0/1`） | **永不** | `_is_system_database()` 硬规则，勾也勾不进去 |
| `business`（其余能读的库） | **总是** | 桶本身 |
| `connection`（`kind: server`） | 不是数据库，不参与 | — |
| `dashboard` | 看板分组，另列 | — |

理由：一个库是否「对外」本来只需要一个答案，原来却有**两个地方**能回答（`enabled` 开关 + 桶），
而 agent 的权限根本不看它（agent 选的是连接，选了就能查这条连接下它角色看得到的库）。

代价（要记住）：现在**没有逐个隐藏**的开关了。想从选择器里拿掉某个 business 库，办法是：删掉它、
改名（前缀 `langconfig` 会被当作 system）、或者把它归到某个不提供库的连接下。如果以后又需要
「库存在但暂时不提供」，那要重新引入一个**单一**开关（并同时从桶推导里退一步），不要再让两处都能答。

## 7. Settings 一致性（2026-11-25，全部 12 个分区）

主题词汇（`SettingsPage.tsx` 顶部）：`SectionTitle` · `Row`（14px 标签 + 12px hint，`padding 12px 0`，
`borderBottom 1px`）· `SubHeading`（12px/500）· `Btn`（primary/ghost/danger，dense）· `Input`/`Select`/
`Toggle`/`Dot` · `Notice`（成功/失败同一通道）· `Empty`（14px muted）· `AddCard`（虚线、radius 12、44px）。

| 分区 | SectionTitle | Row | SubHeading | Btn | AddCard | Notice/Empty | 写死色 | 原生 button | 字号 |
|---|---|---|---|---|---|---|---|---|---|
| General | ✅ | 7 | — | — | — | — | 0 | 0 | 标准 |
| Models | ✅ | 2 | — | 7 | ✅ | — | 0 | 0（AddCard） | 11–14 |
| Search | ✅ | — | — | 5 | — | — | 0 | 0 | 11–14 |
| LocalModels | ✅ | — | — | 6 | ✅ | — | 0 | 0（AddCard） | 11–14 |
| Workspace / Storage / Runtime / Agents | ✅ | 8/1/24/— | — | 2/—/—/— | — | — | 0 | 0 | 标准 |
| Knowledge | ✅ | — | 3 | — | — | — | 0 | 0 | 标准 |
| Ontology | ✅ | — | — | 12 | — | — | 0 | 0 | 11–14 |
| Databases | ✅ | 1 | 1 | 6 | — | ✅/✅ | 0 | 0 | 11–14 |
| About | ✅ | 3 | — | 1 | — | — | 0 | 0 | 14 |

结论：**12/12 分区都有 SectionTitle**；**0 处写死颜色**；**0 个低于 11px 的字号**；剩下 2 个原生
`<button>` 是对话框自己的**导航项与关闭键**（分区导航 / ✕），不是分区内的操作控件，保留原样式；
Models/LocalModels 的「新增」卡片已统一为 `AddCard`（之前一个是 radius 12 + Material 图标、另一个是
radius 22 + `+` 字符——同一个动作两种长相）。

已统一的、但**没有动**的行为差异，需要单独决策：**保存模型**。General/Models/Workspace/Runtime/Agents 是
「改即存」；Ontology/Databases 是显式「保存」。两种并存时用户无法判断刚才那一下存没存——建议二选一，
或采用「标量改即存 + 数组类显式保存，并在标题下写明」的折中。

## 9. 从 26 收敛到 15：这一轮真正删掉了什么（2026-11-25）

前面几轮做的是"标记 + 改名 + 分分类"，**没人真的把死工具拿掉**。这一轮按 usage / binder 证据做了减法。

### 9.1 结果

| 组 | 之前 | 现在 | 手段 |
|---|---|---|---|
| SQL 核心 | 10 | **9** | `db_list_databases` 并进 `db_describe(db_name="")` |
| 平台自省 | 6 | **3** | `pg_list_agents` / `pg_get_agent` / `pg_list_custom_tools` 删除（开发者界面才有意义） |
| Neo4j | 7 | **2** | `neo4j_agent_advanced_tool`（休眠 planner 变体）、`neo4j_query` / `neo4j_get_doc` / `neo4j_upsert_doc` / `neo4j_delete_doc`（0 绑定 0 调用）删除 |
| SQLite | 2 | **0** | 删除；`case-12-csv-chat`（329）已迁到 `db_plan_from_file` + `db_build_from_file` + `db_verify_against_file` + `db_query_agent` |
| 领域校验 | 1 | **1** | `talent_verify_jd_report` 保留 |
| 已退役残留 | 6 | **0** | 物理删除 |

**registry 实测：总数 75；`database 11` / `platform 3` / `data 1` / `retrieval 14`；数据库相关条目 26 → 15。**

### 9.2 细节

- **`db_describe` 吸收 `db_list_databases`**：`db_describe()` 不传库名 = 列这台服务器上的库（实测输出 19 个库 + owner + 大小）。两个入口问的是同一个发现类问题。
- **平台库的 `writable` 标志修正**：合并写入口之后，平台库其实可以行级 DML，但清单里还写着 `[read-only]`——那是 `db_execute` 拒绝平台库时代的说法。现在 `writable=True, write_scope="dml-only"`（`postgres` 仍 `none`）。
- **`case-12-csv-chat` 迁移**：它原来只有 `sqlite_load_csv/sqlite_execute` 这一条数据路径（`["glob","read_any_file","read_file","sqlite_load_csv","sqlite_execute","python_execute"]`）。SQLite 退役前先把它换成 Postgres 路径，否则这个 demo 会失去全部数据能力。
- **技能侧跟着修**：`to-validation` 去掉 `sqlite_execute`；`agent-builder` 去掉 `pg_list_custom_tools` / `pg_get_agent`，正文改成"在 Settings → Tools / Agents 里核对"。
- **门禁改严但分清产权**：`test_no_builtin_skill_allows_a_tool_that_is_not_live` 只对 **builtin** 技能断言——personal 技能是用户自己的内容，测试改它就是改用户数据；personal 的漂移改为**打印报告**。

### 9.3 收尾（2026-11-25，用户逐条拍板）

| 项 | 决定 | 现在的状态 |
|---|---|---|
| `erp-analyst`（personal）写 `sqlite_execute` | **改用 `db_query_langgraph`** | 已改：`allowed-tools: [db_query_langgraph, db_build_from_file, python_execute, web_search]`；正文 5 处旧工具名全替换；开头加了**数据前置**说明——SQLite 工具已移除，先把 ERP 数据用 `db_build_from_file` 建进 Postgres，再用 `db_query_langgraph` 问 |
| `mcp-server-onboarding`（personal）写 `pg_get_agent` 等 | **跳过**（用户决定） | 保持原样。它指向的三个平台自省工具已删除；门禁只对 builtin 断言、对 personal **打印报告**，所以不会让测试红，但警告会一直在 |
| 375 的 `database = null` | **给显式连接** | 已改：`{"mode": "catalog", "name": "local-server"}`；提示词旧工具名同时修掉（`db_query` → `db_query_agent`，看板段改为走本体流水线），并用 `set_agent_prompt.py` 写入（机器尾巴 2 573 字符重建，实测 `prompt_len=6172`） |

**仍然开口的只有一件**：`local-server` 用的仍是 `langconfig` 所有者账号，所以 375 的**权限宽度没变**——变的是"从隐式环境变量变成一条被声明、可在 Settings 里看到和替换的连接"。要真正收窄，得先建一个专门的写角色（能 `CREATE DATABASE`、不能碰平台表），那是独立的一件事。

### 9.4 一个踩到的坑：说明不能写进 frontmatter

给 `erp-analyst` 加说明时，我把 `> **数据前置…**` 插到了 `---` 之内，YAML 把 `>` 当成折叠标量，
于是 `name` / `description` 全被吞掉，`sync_skills` 直接报 `ValueError: Skill description is required for matching`。

**规矩**：SKILL.md 的 frontmatter 只放键值（`name` / `description` / `tags` / `triggers` / `allowed-tools`），
任何正文说明都必须写在**结束的 `---` 之后**；文件也不要以空行开头（解析器要求首字符是 `---`）。

---

## 8. 工具与技能的命名分离（2026-11-25）

数据库这件事在两处表达：**工具**（能力）和**技能**（流程）。它们存在不同的表、由不同的代码加载，
所以改了一边、另一边残留旧名不会报错——这正是下面要固定的原因。

### 8.1 两套命名规则

| 层 | 存储 | 命名 | 例子 | 它提供什么 |
|---|---|---|---|---|
| **工具** | `custom_tools.tool_id` | **snake_case**，数据库族 `db_*` | `db_query_agent`、`db_query_langgraph`、`db_execute` | 真能力：有实现、有守卫（单语句 / 平台库 DDL 拒绝 / 两段式 confirm） |
| **技能** | `skills.skill_id` | **kebab_case**，数据库族 `db-*` | `db-excel-to-postgres`、`db-sql-query`、`db-ontology-build` | 流程与陷阱：顺序、口径、失败模式。**不含任何能力，也不裁剪工具** |
| 平台自省 | `custom_tools`（分类 `platform`） | `pg_*` + `platform` 分类 | `pg_list_agents`、`search_skills` | 读平台自身的表，不是业务库 |

一声明就能看出是否混淆：`db_query_agent` 是工具，`db-sql-query` 是技能。

> **`allowed_tools` 不是过滤器。** 代码里它只被写进 prompt（`core/agents/factory/prompting.py:345`），
> 从不裁剪或授予工具。所以"技能声明了某工具"≠"agent 真有它"；技能写了顺序，工具才有牙齿。

### 8.2 技能改名：旧 → 新（8 个，2026-11-25）

| 旧 skill_id | 新 skill_id | 引用它的 agent |
|---|---|---|
| `excel-csv-to-postgres` | `db-excel-to-postgres` | 1 |
| `sql-query` | `db-sql-query` | 2 |
| `sql-analyst` | `db-sql-analyst` | 1 |
| `sqlite-to-postgres` | `db-sqlite-to-postgres` | 1 |
| `build-ontology-from-db` | `db-ontology-build` | **6** |
| `build-ontology-dashboard` | `db-ontology-dashboard` | 2 |
| `edit-ontology-metrics` | `db-ontology-metrics` | 1 |
| `answer-ontology-question` | `db-ontology-ask` | 2 |

同步改了：`skills` 表 8 行、**13 个 agent 的 `config.skills`**、技能目录（builtin 8 + en-originals 4）、
技能正文与脚本/src/docs 共 **74 个文件**。

### 8.3 事故与正确顺序（值得记住）

改完 `skill_id` 就 `POST /api/skills/reload-all`，这 8 个技能**从库里消失了**（120 → 112）。
根因不是 reload，是 `prune_deleted`：它删除「`source_path` 指向的文件已不存在」的行——而改名时
`source_path` 仍指向旧目录，于是每一条都被判成"技能文件没了"。

**正确顺序**：`git mv 目录` → `sync_skills`（disk → DB，重建行并刷新 `source_path`）→ `reload-all`。
反过来做，就是"文件在、行没了"。实测：按正确顺序跑完，8 个技能回库，`source_path` 指向新目录。

### 8.4 两道门禁（`tests/test_db_tool_and_skill_naming.py`，4 项）

1. **命名**：live 工具 id 必须 snake_case；`db_*` 必须在 `database` 分类；技能 id 必须 kebab_case 且 8 个
   数据库技能带 `db-`；旧技能名不得残留。
2. **漂移（agent）**：agent 的 `native_tools` 里每个名字必须 ∈ {live 工具} ∪ {SDK 原生白名单}。
3. **漂移（技能）**：`allowed_tools` 同规则。
4. 白名单是**显式**的（`SDK_NATIVE_TOOLS`）：加一个名字是一次决定，不是默认。

这道门禁当场抓到两处真实漂移——`to-validation` 的 `allowed_tools` 还写着已退役的 `pg_query`，
`db-excel-to-postgres` 还写着已删除的 `db_dashboard`（磁盘改了、DB 没同步）。同步后转绿。

### 8.5 同一批里删掉的东西

| 项 | 处理 | 依据 |
|---|---|---|
| `db_dashboard`（工具） | 实现 + seed 条目 + 工具行全部删除，375 解绑（12 → 11 个工具） | 与本体看板是两条生成路径，会给两块数字不同的板；它此前每次调用还会抛 `TypeError`（见 §4 看板小节） |
| 技能里的 `db_dashboard` / `pg_query` 引用 | 删除 / 改为现行名 | 同上 + `pg_query` 已退役 |
| `sqlite_execute` / `sqlite_load_csv` | **未动** | 23 / 22 个 agent 绑着、调用 0；按 §4 遗留项处理（case-12 迁 Postgres 后再退役） |

---
