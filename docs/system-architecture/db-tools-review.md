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

### 仍然 OPEN
2. **`sqlite_*`** 两个仍在候选里（4 个 public demo agent 绑着）。我们的栈是 Postgres，SQLite 是遗留演示路径；
   要么把 demo 迁到 Postgres，要么同样标废弃。
3. **`db_dashboard`** 与本体看板（`dashboard.json` + 工作台）是两条生成路径，迟早给出两块不一样的板。留着但
   没有第二个消费者，建议下一步明确它是否退役。

## 5. 连接模型：全局配连接，agent 只选一个（2026-11-25）

**模型**（最小、和 VS Code 一致）：`Settings → Databases` 里配**连接**（名字 + host/port + 用户 + 密码，密码
Fernet 加密存储）；agent 的 Database 设置**只选一个连接名**。一条连接 = 一台服务器，**它下面的所有库都能查** ——
`db_query` 只带库名，`db_list_databases` 列的就是这条连接的库。

### 之前断在哪（实测，2026-11-25）

`config.database` **只喂给 deep agent 的沙箱**（`execute` 里的 psql/脚本），而进程内工具
（`db_query` / `db_review` / `db_describe` / `db_execute`）一律读 `os.environ` 的 `POSTGRES_*`。后果：

- 普通 agent 的 Database 设置**没人读**（`test_db` 就是这种：它的区块是装饰品）；
- 所有进程内 DB 工具都以**部署超级用户**身份运行，任何绑了 `db_query` 的 agent 都能读平台库；
- 还有一层：内置工具的 `implementation_config.code` 是**seed 时嵌入的副本**，改 `tools/native_impl.py`
  不会影响正在运行的 `db_query`，必须 `seed_builtin_tools.py --refresh` 重新生成行。

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
