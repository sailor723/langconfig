---
name: "Answer Ontology Question（用本体回答问题）"
lang: zh
translated: machine
source: backend/skills/en-originals/answer-ontology-question/SKILL.md
description: >-
  客户（或同事）用自己的话提问，而答案必须是业务能够为之辩护的一个数字时使用：对着本体声明的内容澄清意图，让编译器
  生成 SQL，用护栏把它圈住，并且只在数字验证通过之后才润色文字。这不是"给这个问题写条 SQL"。
tags: [ontology, natural-language, intent, sql, guardrails, answer]
triggers:
  - "一个业务问题到来，而答案必须来自本体、不能来自手写 SQL 时"
  - "同一个问题给出两个不同数字，必须由定义来裁决时"
  - "必须拒绝作答，因为本体回答不了它（而拒绝必须说明原因）时"
  - "必须从用户真正打出的词里解析出指标 / 类 / 动作的名字时"
version: 1.0
author: weiping

params:
  ontology_key:
    label: 本体
    description: 由哪个本体回答问题（它的 Query 部分）
    required: true
  workbench:
    label: 工作台地址
    description: 该本体工作台的 URL，例如 http://127.0.0.1:8098
    required: false
---

# 用本体回答业务问题

**这条流水线活在每个本体里，而不在某一处。** 每个本体都有自己的工作台，工作台服务于该本体自己的 **Query** 部分
（`<workbench>/query`，由 `POST /api/nl` 支撑）——流水线是同一份代码，但*菜单*、*样例*、*别名*、*标签*和*教程*
属于那个本体。所以"回答一条客户查询"永远意味着"对着**这个**本体的声明来回答"，而第一步是搞清楚自己在哪个本体里。

`retail_graph/`（`nl.py`、`sqlgen.py`、`capability.py`、`guard.py`、`lane_b.py`）是这条流水线的**参考实现**，
下面这些锚点因此都指向那里；每个本体自己的资产放在 `ontologies/<key>/`（`*_settings.json` → `samples`、
`aliases`、`ns`、`dsn`、`guard`）。

本技能讲的是这条流水线的形状，顺序就是让数字保持诚实的那个顺序。模块锚点、意图 JSON、槽位类型和护栏旋钮见
[references/pipeline.md](references/pipeline.md)；在因为一个奇怪的答案去怪本体之前，先读
[../build-ontology-from-db/references/tuning-log.md](../build-ontology-from-db/references/tuning-log.md)——
大多数奇怪的答案都是匹配失败，那里把它们编了目。

**决定其余一切的那条规则：模型永远不写 SQL，也永远不做计算。** 它从菜单里挑一个名字，然后围绕编译器产出的数字写文字。
所有涉及数字的东西都是编译出来的。

## 四个阶段

### 1. 接住问题——逐字，用用户的语言

保留原话。不要先"清洗"问题：这些词是第 2 阶段的证据，而在匹配之前就被改写的问题，是没人能审计的问题。记下语言
（它决定答案的语言），以及它是一次读（一个数字）还是一次写（一个动作）。

### 2. 澄清意图——受菜单约束，规则优先

从本体拼出菜单：指标（名字、标签、定义、编译出的 SQL）、类（名字、标签、由什么定义）、动作（名字、参数、编译成的
护栏）。然后按这个顺序来：

- **规则优先**（~0 ms）：camelCase 名字上的 token 重叠、作者写的 `rdfs:label`、profile 的 `aliases`，再加上从
  编译出的 SQL 里取的聚合提示（`count(`、`sum(`、`max(`）。动作需要一个显式的**动词**（`promote`/
  `record`）——名词绝不能选中一个动作。
- **一个数字只能由指标回答，否则按名拒绝**——绝不用一串类清单作答。度量线索：数 / 多少 / 几条 / 率 / 占比 / 金额 /
  最多 / 最高 / 排名，以及 count / sum / rate / how many。*已声明*的计数必须找到它自己的指标（`订单数` →
  `orderCount`），即使类名更短；中文名词的修饰语在前，所以 `高风险线路`（后缀 `线路`）能命中，而 `订单行`
  （只有前缀）不能。
- **字面标签是终局**：如果问题里逐字出现了某条声明的 `rdfs:label`，那就是存在的最强证据——任何东西都不得否决它
  （`每千公里破损箱数是多少` 必须到达恰好带着这个标签的那个指标）。
- **维度**："按 X" / "by X" 必须解析到一个按 X 分组（`GROUP BY` X）的指标，否则就带着可分组的指标清单拒绝。悄悄
  丢掉维度，等于回答了另一个问题。
- **槽位**（`:supportsSlot :TimeWindow` / `:CustomerFilter`）：问题里的时间段和客户变成参数，而不是 SQL。复杂的
  意图（任何槽位，或一个动作）要**作为理解回显出来，并在执行前需要一次确认**——这个回显是成本最低的错答案检查。
  窗口过滤的是该指标粒度类自己的 `:timeColumn`（声明在类上，例如 `:Trip "trip_date"`）；没有这条声明的粒度
  **按名拒绝**，绝不在缺窗口的情况下作答。`ratio_of_sums` 指标目前还带不了窗口——宁可拒绝，也不要给它一个半截窗口。
- **只有当规则拿不准时**模型才上场，而且它只能从菜单里返回 `{kind, name, params}`。菜单之外 → 按名拒绝，并列出
  菜单上有什么。
- 在执行任何东西之前，把选中的名字和参数类型对着菜单**校验**一遍。
- **问题里说出的约束必须一路带下去，绝不丢**：如果问题说了"最近 90 天"或点名了某个客户，这条约束就必须到达 SQL
  （作为参数下推），否则这个问题必须被拒绝。实测失败：模型路径返回的意图没有槽位，SQL 里没有 `WHERE`，于是一个
  明确说了时间段的提问，答案成了全时段总量。`nl._ask` 现在会把说出的槽位重新挂上，让 `capability.resolve` 接受
  或拒绝；它这么做时，追踪里会出现 `2b · slots` 一步。

两个不同指标同时匹配，不是一场可以悄悄裁定的平局：说出是哪两个，并问用户指的是哪个定义（粒度不同 = 数字不同）。

### 3. 执行——编译、圈住、跑起来

永远不写 SQL。意图送到本体自己的编译器：

- 指标 → `compile_metric`（连接来自 `:references`，粒度来自 `:grain`，行集来自 `:where`，维度来自 `:groupBy`，
  比率来自 `:numerator`/`:denominator`）；
- 类 → `concept_sql` / 该公理的谓词；
- 动作 → 一次**试运行**（`actions.check_action`），报告 ADMITTED / REFUSED；真正的写只在显式确认之后，通过受审计
  的通道发生。

然后是护栏，它们不是可选项：行数上限、执行计划预算、语句超时、带自己时间列的大表。**已声明的指标永不加窗口**——
护栏报出无界扫描，由执行计划预算来裁；往一个指标里注入"最近 90 天"的窗口，会悄悄改变它定义所承诺的那个数字
（实测：定义说 4,050，结果 3,950）。

### 4. 润色——数字之后再写文字，而且要验证过

模型可以把答案改写成可读的文字。改写之后要**机械地检查**，不合格就丢弃：

- 每一个算出来的数字、每一个结果键都**逐字**出现；
- 分组答案里，每一个键**及其**值都还在；
- 动作答案里重复那个 **ADMITTED / REFUSED** 判定；
- 答案用的是**问题的语言**。

润色不合格就被扔掉，改由确定性模板作答——用户照样拿到正确的数字，而追踪会写明这段答案是谁写的。拒绝和
理解回显也走同一套检查。

## 第二条通道：在同一批定义上跑 SPARQL

零售参考实现跑通道 B——由 Ontop 在同一批表的 R2RML 映射上回答 SPARQL（`retail_graph/lane_b.py`、
`check_mapping.py`）。它存在的意义是证明那些声明，而不是替代编译器：

- 在两条通道里问**同一个**问题并对比（类计数：通道 A 编译 vs 通道 B SPARQL）；
- 映射写错是这里最大的静默失败——门禁会查它（M4：每个被服务的已定义概念的谓词都编码进映射 SQL；M5：两条通道
  之间在真实数据上的一致性）；
- **不可用不等于通过**：没有端点、没有映射、或者没有 Ontop 栈 ⇒ 报
  `NOT RUN (no R2RML mapping for this dataset / the endpoint is down)`。永远不要用 SQL 通道回答一个 SPARQL
  问题，然后把它叫作通道 B。

## 作为智能体跑这套流程

`logics_query` 智能体（由 `scripts/seeds/in/seed_logics_query_agent.py` 播种）就是这个技能加一个工具：
**`ontology_ask(question, ontology_key, confirm)`**——一次调用背后是整条流水线（菜单 → 规则优先的意图 → 校验 →
编译 → 护栏 → 验证过的文字），返回数字及其定义与编译出的 SQL，或者一个**按名**的拒绝，或者带着那份理解的
`needs_confirmation`。

它故意**不带发布工具，也不带写文件的工具**：一个能改动自己所依据本体的回答智能体，会让它报告的每个数字都可疑。
它的本体来自 `skill_params`，不是来自散文：

```json
"skills": ["answer-ontology-question"],
"skill_params": {"answer-ontology-question": {"ontology_key": "logistics",
                                              "workbench": "http://127.0.0.1:8098"}}
```

## 样例是前端入口，而且它们有门禁

profile 的 `samples` 是用户最先点的那批问题。profile 旁边的 `samples.json` 说明每一个必须产出什么——一个值、
一组分组行，或者一个**按名**的拒绝——`check_samples.py` 把它们逐个跑过这条流水线（`--profile … `，退出码 2 =
拒绝且被门禁承认，退出码 1 = 某个样例失败）。`check_ontology_generic.py` 把它当作 `S` 门禁来跑，所以一次破坏
样例的发布落不了地。

那个文件有三条规则：

- 期望数字来自**第二条路径**（手写 SQL），不来自这条流水线自己的输出；
- `expect: {"unresolved": "…"}` 是一个**记录在案的待办项**——本体还兑现不了的样例，每次运行都会打印，带上缺失的
  那条声明，以及第二条路径给出的数字。它永远不算通过；
- 没人检查的样例才会烂掉：凡是提供了、却不在 `samples.json` 里的问题，`check_samples.py` 都会告警。

## 这样报告

```
Q: 按线路版本看破损箱数          (interpreted as metric :damagedBoxesByRouteVersion, rules)
A: v1 = 3,490 · v2 = 4,654       (compiled SQL below; guard: page cap only, no window)
   definition: :damagePer1kStops' sibling — sum of stops.damaged_boxes grouped by routes.version,
   joins from :tripOf and :routeOf
   polished by: template (polish rejected: a number changed)   ← says which one answered
REFUSED  atRiskDrivers: :AtRiskDriver has no owl:equivalentClass axiom — nothing to compile
NOT RUN  lane B parity: no R2RML mapping for this dataset
```

- 那个数字**以及**它来自的那个定义；
- 编译出的 SQL（读者必须能看清用了哪些连接）；
- **按名**的拒绝，当作待办清单——它们是与业务的谈判；
- `NOT RUN` 的条目要点名，绝不悄悄变绿；
- 是哪个阶段答的（规则 / 模型）、文字是谁写的（llm / 模板）。

## 这个技能拒绝做的事

- 为某个问题**手写 SQL**，任何情况下都不——包括"就这一次，这样更快"；
- 为了作答**发明一个指标**：没有声明的问题就是一次拒绝加一条待办；
- 为了让查询便宜而**给已声明的指标加窗口**，或者为了让数字冒出来而**放宽护栏**；
- 问题要的是数字，却**用一串类清单作答**；
- **相信润色**：一次没检查过的改写，就是报告里数字变样的方式；
- 因为另一条通道答出来了，就**宣布某条通道"通过"**。

## 前提条件（由宿主提供，不由本技能提供）

| 能力 | 为什么 |
|---|---|
| 本体仓库的编译器（`sqlgen.py`、`capability.py`、`guard.py`、`nl.py`） | 流水线*就是*这些模块；本技能只是它们的顺序 |
| 该 profile 的 PostgreSQL 连接 | 数字来自数据库，而不是关于数据库的描述 |
| 一个模型后端（DeepSeek 或本地 Ollama）——**可选** | 规则 0 ms 就能答；模型只用于拿不准的解析和写文字，绝不用于 SQL 或算术 |
| `scripts/ask.py` | 把一个问题的五个阶段全跑一遍并打印追踪（退出码 2 = 拒绝） |

```bash
PY=<the app's own .venv: the interpreter that runs the backend>
$PY scripts/ask.py --profile <ontology>/<key>_settings.json "这句话就是用户问的原话"
$PY scripts/ask.py --profile … "按线路版本看破损箱数" --json        # full trace
$PY scripts/ask.py --profile … "订单收入" --no-polish               # deterministic prose only
$PY scripts/ask.py --profile … "上个月的行程数" --confirm            # a slot question, confirmed
```
