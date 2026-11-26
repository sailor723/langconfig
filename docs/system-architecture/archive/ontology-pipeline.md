# Excel → 库 → 本体 → 看板：总体设计

状态：**分层实现**，每一层都注明「已实现并验证 / 已设计未建」。写这份文档的目的不是描述理想，而是把每一块的
**边界、契约和失败模式**固定下来，让下一步可以只改一处而不动其它。

阅读顺序：§1 目标与用户流 → §2 分层总图 → §3 agent 拓扑与职责 → §4 交接契约 → §5 运行时机制 → §6 写入与
版本层 → §7 发布通道与门禁 → §8 文件/数据布局 → §9 失败模式与护栏 → §10 证据与验证 → §11 部署 → §12 开放决策。

---

## 1. 目标与用户流

**用户只说一句话**：「这是我们的 Excel，做成能看的东西。」系统要把这句话变成：一个**可编译、可拒绝、可复核**
的本体 + 一块**每个数字都能追到声明**的看板，且中途**两处必须停下来问人**。

```
用户上传 Excel
   │
   ├─ STOP-1  grill（前沿清空之前不动手）─────────────── 人
   │
   ├─ 建库（Excel → PostgreSQL，先出方案再建）
   ├─ 建本体（S0 草图 → S1 结构 → S2 含义 → S3 指标 → S4 护栏 → S5 样例）
   ├─ 建看板（S6 dashboard.json → S7 教程 → S8 拒绝清单）
   │
   └─ STOP-2  publish（staged → 人 confirm → apply）──── 人
```

两条铁律贯穿全篇（来自既有实践，不是本设计的发明）：

1. **声明是唯一真相**：数字由声明编译出来；改声明数字才动；想让门禁变绿就改期望值，是作弊。
2. **不能问人「拒绝」**：没有对应字段的能力写进拒绝清单，按名给理由；未知 ≠ 不合格。

---

## 2. 分层总图

```
┌──────────────────────────────────────────────────────────────────────┐
│ L4 对话层   manager agent（唯一有用户通道的 agent）                    │
│             grill · 汇总 · 登记 · 发布 · 汇报拒绝清单                   │
├──────────────────────────────────────────────────────────────────────┤
│ L3 劳动层   4 个 subagent（各自独立上下文，只能读文件、只回一条消息）    │
│             tables │ modeller │ metrics │ board                       │
├──────────────────────────────────────────────────────────────────────┤
│ L2 契约层   文件即接口：work/<key>/ · _brief.md · grill.md · NOTES.md    │
│             返回即契约：response_format JSON {produced, unverified, …}   │
├──────────────────────────────────────────────────────────────────────┤
│ L1 声明层   profiles/<key>/：01-structure.ttl · 02-meaning.ttl ·       │
│             metrics_ext.ttl · samples.json · dashboard.json · tutorial   │
├──────────────────────────────────────────────────────────────────────┤
│ L0 平台层   编译器 · 门禁（check_*）· 发布通道（stage/apply）· 工作台    │
└──────────────────────────────────────────────────────────────────────┘
```

关键：**L4 不写声明，L3 不碰用户，L1 不跑自己的门禁**。每一层只拥有自己那一件事。

---

## 3. Agent 拓扑与职责

### 3.1 manager（`Ontology Pipeline`）

| 项 | 内容 |
|---|---|
| 工具 | `task` · `write_todos` · `read_file` · `ls` · `ontology_inspect` · `ontology_register` · `ontology_publish` |
| pin 技能 | `grilling`（问人）—— **不 pin** `grill-me`（它只是指向 `grilling` 的指针，多一跳） |
| 拥有 | 两处停点、版本号分配（通过 register）、发布（staged）、拒绝清单汇报 |
| 禁止 | 写 TTL / `dashboard.json`、量数、替专家做决定 |

### 3.2 四个专家

| 专家 | 做什么 | 工具子集 | 产出 |
|---|---|---|---|
| `tables` | Excel/CSV → PostgreSQL：先 `db_plan_from_file` 出方案，人确认后 `db_build_from_file(confirm=true)`，再 `db_verify_against_file` 逐值对账 | `read_any_file` `db_plan_from_file` `db_build_from_file` `db_verify_against_file` `db_review` | 真库 + 建库标记 + 对账报告 |
| `modeller` | S0 草图 → S1 结构 → S2 含义 | `ontology_open` `ontology_inspect` `read_file` `write_file` `edit_file` `execute` `db_query` | `01-structure.ttl` `02-meaning.ttl` |
| `metrics` | S3 指标 → S4 护栏 → S5 样例（**只追加**） | 同上 | `metrics_ext.ttl` `samples.json` |
| `board` | S6 看板 → S7 教程 → S8 拒绝清单 | `ontology_inspect` `read_file` `write_file` `edit_file` `execute` | `dashboard.json` `tutorial.json` |

**`metrics` 的只追加规则**：它可以新增指标、护栏、样例，**不得改结构**。需要改结构 → 回 `needs_human`，由
manager 重新派 `modeller`。理由：把一份连贯的模型切成两个上下文，最大的风险是**声明漂移**（结构说一种粒度，
指标按另一种算）；`ontology_publish` 跑全族门禁是最后仲裁，但不能替代这条规则。

### 3.3 为什么 grill 不是 subagent

`grilling` 的产出是**对话**（问一轮、停下等、答案重塑决策树、再问下一轮）。subagent 只见 task 提示词、只回
一条最终消息，**看不到用户的回答**。所以 grill 只能由 manager 做；grilling 里「派子智能体去查事实」正好派给
`tables`（`db_plan_from_file` 不建库，很便宜，且它产出的正是「待确认点」）。

---

## 4. 交接契约

### 4.1 文件是唯一共享内存

deepagents 的 subagent 与父 agent **共享 backend（文件系统），不共享 messages**；父 agent 只收到子 agent 的
**最后一条消息**（或 `response_format` 的 JSON）。源码依据：`deepagents/middleware/subagents.py` 的
`_EXCLUDED_STATE_KEYS = {"messages", "todos", "structured_response"}`，以及每个 subagent 都用
`FilesystemMiddleware(backend=backend, …)` 构建。

因此**决定必须落盘**，否则等于没定：

| 文件 | 谁写 | 谁读 | 内容 |
|---|---|---|---|
| `profiles/<key>/_brief.md` | `ontology_register` | 全部专家 | 名字、key、库名、主题、kind（输入，不是声明） |
| `work/<key>/grill.md` | manager | modeller/metrics/board | 每个决定 + 答案 + 一行理由 + **有意未定项** |
| `work/<key>/NOTES.md` | 每个专家追加 | 下一个专家 + manager | 产物、未验证项、需要人决定的项 |
| `work/<key>/*.ttl`、`dashboard.json` | 对应专家 | 发布通道 | 声明本身 |

### 4.2 返回值是契约，不是散文

每个专家带 `response_format`（`SubAgentConfig.response_format` 已支持，dict schema）返回：

```json
{"produced": ["work/orders_v1/metrics_ext.ttl"], "facts": ["订单表 6 行 · 金额 NUMERIC"],
 "unverified": ["金额单位未确认"], "needs_human": ["退货率的分母是订单数还是订单行数？"]}
```

manager 靠这三个字段判断能不能往下走，**不需要**读专家的工具输出（这正是 context quarantine 的意义）。

### 4.3 两处停点

| 停点 | 位置 | 条件 | 之后的动作 |
|---|---|---|---|
| STOP-1 | grill 之后、建库之前 | grilling 输出「前沿已空」+ 用户确认方案与口径 | 派 `tables` build |
| STOP-2 | publish 之后、apply 之前 | `ontology_publish` 停在 staged，人工在 Settings → Ontology 确认 | 平台 apply（再跑门禁、字节级备份后提交） |

STOP-1 用对话（问不到 `interrupt_on`，因为它是**语义**决定）；STOP-2 可以配 `interrupt_on=["ontology_publish"]`
做硬闸，但发布通道本身的 staged/apply 已经是硬闸，优先用它。

---

## 5. 运行时机制（映射到 deepagents 0.7.1）

| 需求 | 机制 | 备注 |
|---|---|---|
| 计划不是散文 | `TodoListMiddleware` → `write_todos` | 默认栈自带 |
| 大输出不进 manager 上下文 | subagent + `response_format` | 父只见最终消息 |
| 真实文件 + `execute` | `LocalShellBackend`（LangConfig 已用 `use_local_sandbox`） | `permissions` **不覆盖** `execute` |
| 每级独立预算 | 每个 subagent 自己的 summarization + 栈 | 单回合 300 步上限，一级一回合 |
| 结构化回执 | **不用 `response_format`**：见下方「实测踩到的三个坑」 | `mode: "fork"` 尚无 |
| 人工硬闸 | `interrupt_on`（需 checkpointer） | 只在写入类工具上用 |
| 技能按需加载 | `skills=[...]`（每 subagent 各自 `SkillsMiddleware`，**不继承**） | 专家各自 pin `build-ontology-from-db` |
| 记忆常驻 | `memory=["AGENTS.md"]` | 放硬规则（10 条），不放流程 |

### 实测踩到的三个坑（2026-11-25，真回合）

设计写得再顺，这三个都是跑起来才暴露的，且每一个都会**静默毁掉整个架构**：

1. **`task` 有两个实现，平台那个是占位。** `tools/native_impl.py` 的 `task` 返回
   `"[SUBAGENT TASK QUEUED] … the framework will route this"` —— **没有任何东西会路由它**。它一旦进了
   `native_tools`，就盖住了 `SubAgentMiddleware` 真正的 `task`（实测：编译图里的 `task` 描述里写的是
   "e.g. research / code / writer / general"，我们的四个专家一个都没出现）。**修法**：manager 的
   `native_tools` 里不写 `task`，让 SDK 自己的那个成为唯一的。
2. **`general-purpose` 会被自动加进来。** 只要没有同名 spec，SDK 就补一个「拥有主 agent 全部工具」的兜底
   —— 管理者绕过四个专家的后门。**修法**：自己给一个同名 spec，描述写「【禁用】」，prompt 只回一句
   「请按台阶改派」—— 名字被占住，兜底就不会生成（不用动全局 harness profile 注册表，那会波及同模型的所有
   agent）。
3. **结构化输出在这台机器上不可用。** `response_format` 传 JSON schema dict 时：不带顶层 `title` 直接
   `Unsupported function`；带了 `title` 会变成 `ToolStrategy`，而它是**强制 `tool_choice`**——本部署的
   deepseek-v4-flash 在 thinking 模式下回答 `Thinking mode does not support this tool_choice`。两次都是
   **子 agent 已经被选中之后**才失败，所以看起来像「派了活但没回执」。**修法**：回执改成 prompt 合同
   （专家最后必须给一个 ```json 回执块```），管理者没有回执就当作没做完、重派一次。

**必须验证而不是假定**（否则设计只是纸面）：

1. `general-purpose` 默认 subagent 不出现在 `task` 列表里（否则 manager 可以绕过 4 个专家）；
2. `tables` 写的文件 `modeller` 能读到（同一 backend）；
3. `response_format` 的 JSON 真的作为 tool message 内容回来；
4. 撞步数上限的专家**大声失败**回到 manager，不静默截断；
5. UI 里能看到派活与回执（`messages.py` 已把 `task` 作为 `tool_start` 呈现，子 agent 内部 token 需要
   `subgraphs=True`，当前没有 → 一级运行期间是黑箱，靠 `NOTES.md` 留痕）。

---

## 6. 写入与版本层

### 6.1 客户给名字，平台给版本（已实现，32 项测试）

`features/ontology/versioning.py`：`<base>_v<N>`，N = registry ∪ `profiles/` ∪ `gates.json` 最大值 +1，**永不复用**；
每族一个 `latest`，旧构建保留 `superseded_by`；`kind ∈ {customer, demo, trial, tutorial}`。

### 6.2 登记（已实现，21 项测试；尚未接到 agent）

`services/ontology_register.py`：一次调用写四处 —— `profiles/<key>/`（profile 骨架 + `_brief.md`）、
`gates.json`（`pending_install`）、Settings → Ontology 行（带 version/kind/latest）、`_versions.json`。

三条设计要点：
- **骨架不发明决定**：`guard.big_tables` / `default_window_days` 刻意不写（那是 S0/S4 的实测结论）；
- **不带口令字面量**：dsn 引用 `${ONTOLOGY_DB_*}`（门禁 X2 会拒字面量）；
- **重试不是新版本**：latest 已登记但没建（无 `01-structure.ttl`）时，再调返回同一个 key，不铸 v2。

---

## 7. 发布通道与门禁

```
work/<key>/*.ttl  ──ontology_publish──▶  stage()
                                          ├─ 备份已安装版本 → 暂存副本
                                          ├─ 逐指标编译（compiler）
                                          ├─ 跑 gates.json 声明的族
                                          ├─ new_refusals / carried 分开列
                                          └─ 停在 staged  ──人 confirm──▶ apply()
                                                                          ├─ 再跑门禁
                                                                          ├─ 字节级备份
                                                                          └─ git commit（平台身份）
```

- **agent 永远不能 apply**，这是设计：不对称才是重点（agent 干活，人决定含义变更）。
- 门禁族：`check_structure` `check_ontology_generic` `check_samples` `check_dashboard`（+ ABox 两个，若声明）。
- `profiles/<key>/dashboard.json` → `services/ontology_dashboard.py` → 工作台面板；`check_dashboard` 负责
  「每个面板引用已声明指标或已声明的洞」。

---

## 8. 文件与数据布局

```
backend/features/ontology/
  gates.json                 ← 每个 key 的门禁族声明（pending_install → 构建后清掉）
  versioning.py              ← 版本规则（唯一分配数字的地方）
  profiles/
    _versions.json           ← 登记表：base → latest + 版本链 + kind
    <key>/
      _brief.md              ← 登记时的事实（输入）
      <key>_settings.json    ← ns/dsn/guard/features（声明之外的配置）
      01-structure.ttl 02-meaning.ttl metrics_ext.ttl
      samples.json dashboard.json tutorial.json
backend/services/
  ontology_register.py       ← 登记（写仓库四处）
  ontology_publish.py        ← stage/apply/ledger
  ontology_dashboard.py      ← dashboard.json → 面板
backend/outputs/users/<n>/agents/agent_<id>/   ← agent 的沙箱（upload/ work/ generated/）
```

**边界**：agent 只能写自己的沙箱；`profiles/`、`gates.json` 只有**平台服务**（`ontology_register`/`publish`）能写。
这正是 grill 里「先读声明文件」必须翻译成 `ontology_open`/`ontology_inspect` 的原因——沙箱里看不见仓库。

---

## 9. 失败模式与护栏

| 失败模式 | 谁挡住 |
|---|---|
| 方案映射错误（列类型、缺表头、重复表头） | `db_plan_from_file` 出方案 + STOP-1；`db_verify_against_file` 逐值对账 |
| 库名打错 → 空本体 | `ontology_register` 探库（`database does not answer`） |
| 定义漂移（结构 vs 指标） | `metrics` 只追加规则 + publish 全族门禁 |
| 专家自己拿主意（用户该定的） | 专家无用户通道，只能 `needs_human`；决定只从 `grill.md` 来 |
| 声明写进不存在的 key | `ontology_publish` 校验 key/路径；`stage()` 拒绝对路径与 `..` |
| 悄悄把门禁改绿 | 只读沙箱 + 门禁期望值在仓库；publish 记录 new_refusals |
| 一次做完 S0–S8 撞步数 | 一级一回合（`recursion_limit=300` ≈150 次工具调用） |
| manager 绕开专家 | 关掉 `general-purpose`（待验证） |
| 长回合「没问题」但没产物 | 交付物是文件 + `produced[]` 字段；门禁与对账是外部仲裁 |

---

## 9b. 让 truth / 门禁真的跑起来（2026-11-25，全流程演练暴露）

`store_monthly_v1` 跑通后剩下两处 `NOT RUN`，都不是「先放着」：一处是声明缺文件，一处是门禁写得只认
logistics 的表名。修法都落在**通用性**上，不是给某个本体开后门：

| 问题 | 修法 | 证据 |
|---|---|---|
| `R2 definition == hand SQL` 永远 NOT RUN（没 `truth.json _definitions`） | 声明一个**定义类** `:ReturnedStoreMonth`（谓词式，`退货额 > 0`）+ 用它作 `:where` 的计数指标 + `truth.json` 的 `_definitions` | R1/R2 真跑：`[PASS] R2 :ReturnedStoreMonth entails 退货额 > 0`（12 vs 12） |
| 定义类过不了 `check_structure`：`names :primaryKey`、`no class is property-less` | `check_structure` 对**定义类**（有 `:physicalPredicate` / `owl:equivalentClass`）豁免 S1a/S1b3 | 定义类没有列也没有自己的主键；要满足这两条只能重复声明基类主键、再给同一列起第二个属性名 —— 那正是 S1d「一个属性名只属于一个 domain」禁止的 |
| `D3` 十二个恒等式只认 `tripCountByWeek` 等 logistics 指标 | 看板可**自己声明** `identities`（`{grouped, whole, width?, weights?}`）；声明了自己的，就不再跑内置清单 | 5 条真跑：营业额按门店/按月加总 = 合计、客流按门店、退货率（**营业额为权**）、客单价（客流为权） |
| `D5` 的第二路线写在门禁里、且只认 logistics 表 | 看板可声明 `independent_sql`：`{label, sql, metric}`，**指名它验证哪个指标**，门禁就真的比 | 4 条真跑：`revenueTotal` / `trafficTotal` / `returnRate` / `avgTicket` 与手写 SQL 相等 |
| `independent_sql` 只被塞进 truth、从不比较 | 上一条的同一个修法：加了 `metric` 字段后才进比较循环 | 之前「声明了 4 条第二路线，一条都没比」——检查跑起来却什么都没证明 |

量纲这条值得单独记：**第二路线必须与声明的单位一致**。`returnRate` 声明 `:unit percent` + `:scale "100.0"`，
编译值 2.214269；手写 SQL 若不自乘 100 就得到 0.022143，D5 判红——第一次就是这么红的，改的是手写 SQL
（乘 100、round 6 位），不是把门禁放宽。

仍然 NOT RUN（都是**前提不适用**，不是漏做）：

- `window gate: no metric declares :supportsSlot :TimeWindow` —— 本库唯一时间列是 **TEXT** `月份`
  (`YYYY-MM`)。`TimeWindow` 会编译成 `月份 >= now() - interval`，在库里直接类型报错；趋势线按 `:month`
  分组即可。声明它才是错的。
- `F1` 交叉过滤 —— 这块板**没有可过滤维度**（`emit_filter` 空）。现在它写成一条**声明式 scope**：
  `dashboard.json` 的 `no_filterable_dimension: true`（或 `filters: []`），F1 于是判
  `PASS the board declares no filterable dimension — and emits none`，而不是 NOT RUN ——
  **并且声明必须与面板一致**：一旦某个面板 `emit_filter`，同一条会判红。声明了自己的 scope，就不再跑
  内置的 logistics 维度（routeVersion / storeZone / liability），那三条只属于那块板。

## 10. 证据与验证

| 层 | 验证方式 | 现状 |
|---|---|---|
| 版本编号 | `tests/test_ontology_versioning.py`（32，含变异测试） | 绿 |
| 登记 | `tests/test_ontology_register.py`（21） | 绿 |
| 技能参数作用域 | `tests/test_skill_params_scope.py`（5） | 绿 |
| Excel → 库 | 真文件：2 sheet → 2 表，`Row counts match`，逐列和对 PASS | 绿（本机实测） |
| 单个 builder agent | 真对话：不猜 key、`ontology_open` 取库名、24 表 / 2 087 行与独立 `count(*)` 一致 | 绿（本机 + ECS） |
| 门禁全套 | `python -m scripts.ontology_gates` | 60 runs · 8 failed · 40 NOT RUN（与干净 HEAD 完全同集，均为环境/声明问题） |
| manager + 5 | — | **未建** |

---

## 11. 部署形态

- 本机：`uvicorn main:app --host 0.0.0.0 --port 8765 --workers 1`；前端 `npm run build`，dist 由后端服务。
- ECS `8.216.56.149`：`git pull --ff-only` + `alembic upgrade head` + `systemctl restart langconfig`；
  `seed_all.py` 的 `[10.7/10]` 会注册唯一的 `Ontology Builder`（幂等，凭据总取本机 `.env`）。
- 出厂快照 `deep_agents_merge.sql` 里 builder 行的口令是 `null`（导出脱敏）→ 新装机器必须跑 seed 第 10.7 步。

---

## 12. 开放决策与下一步

1. **实现 manager + 4 专家（含 grill 步骤）**：先骨架 + 5 项运行时验证（§5 列表），再放一个真实 key 跑通。
2. **`general-purpose` 关闭方式**：注册 harness profile（beta API）还是用一个同名 spec 顶替——先验证再选。
3. **`grill.md` 与 `_brief.md` 的关系**：前者是「这次讨论定了什么」，后者是「登记时已知的事实」；
   同一条事实出现两处时要有一条优先级（建议：`_brief.md` 是事实，`grill.md` 是决定，冲突以 grill 为准并回写 brief）。
4. **`new_coldchain_v7`**：做完，还是删声明（号继续占住）。
5. **工具实现搬家**：`seed_ontology_*_tool.py` 里的代码字符串 → `backend/tools/ontology_*.py`。
6. **`mode: "fork"`** 升级到支持它的 deepagents 版本后，可让 `metrics` 直接看到 ST0 草图，省一个文件往返。
