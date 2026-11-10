---
name: "edit-ontology-metrics（修改本体指标）"
lang: zh
translated: machine
source: backend/skills/en-originals/edit-ontology-metrics/SKILL.md
description: "被要求改动一个已经存在的本体时使用——新增或修正一个指标、改变某个数字的含义、重命名一个属性、调整护栏配置或样例——而不是从数据库搭一个新的。它打开已安装本体的一个副本，只改拥有这次变更的那一个文件，用第二条 SQL 路径验证数字，然后通过发布通道交回来（只做暂存；由人来应用）。"
tags: [ontology, semantic-layer, metrics, edit, gates, publish]
triggers:
  - "被要求新增、修改、修正或删除一个既有本体里的指标时"
  - "「这个数字不对 / 没有 / 不是我们要的」而它是本体定义的指标时"
  - "要调整护栏配置、样例或属性名时"
version: 1.0
author: weiping

params:
  ontology_key:
    label: 本体
    description: 这个智能体要改的本体（features/ontology/profiles/ 下的文件夹）
    required: true
  repo:
    label: 本体仓库
    description: 可选——本体学习用镜像所在的位置。不设置表示使用本应用自己的
      feature（backend/features/ontology），编译器、门禁和 profile 都在那里。
    required: false
    default: ""
---

# 修改一个已经存在的本体

一次修改不是"给它写条 SQL"。本体的数字是从声明*编译*出来的，所以整件事就是：找到拥有这个数字的那条声明，改
**它**，然后证明它产出的那个数字。其余的一切——工作台、报表、以后每一个问题——都跟着走。

**动一条声明之前，先读
[../build-ontology-from-db/references/rules.md](../build-ontology-from-db/references/rules.md)。** 它是那十五条
配置规则以及每条规则防住哪种失败的唯一出处。本技能不重复它们。
[references/metric-recipes.md](references/metric-recipes.md) 收录了真正需要声明的那三种形状——分母落在另一个
对象上的跨粒度比率、维度隔着两跳的分组指标、两个维度四张表的分组——每种都带 TTL、编译器推出的 SQL，以及在一个
真实本体上量到的值。而
[../build-ontology-from-db/references/tuning-log.md](../build-ontology-from-db/references/tuning-log.md) 是
智能体在这里真犯过的失败记录（去读引擎、拿类去回答计数、否决一个标签）——在因为一个糟糕答案去怪本体之前先读它。
有东西拒绝时读
[../build-ontology-from-db/references/pitfalls.md](../build-ontology-from-db/references/pitfalls.md)，
门禁矩阵（包括最后那道发布门禁）见
[../build-ontology-from-db/references/gates.md](../build-ontology-from-db/references/gates.md)。

## 问编译器，不要去读它

`ontology_inspect(ontology_key="logistics")` → 每个指标，以及每一个**按名**的拒绝。
`ontology_inspect(ontology_key="logistics", metric="tripCount")` → 编译出的 SQL、护栏下的值、执行计划估算、护栏
的备注——或者编译器那句拒绝。`…, question="有多少条线路"` → NL 层把它解析成什么，逐字给出。
`…, source_dir="work/logistics"` → 同样的这些问题对着你的**副本**跑，所以一次修改的前后对比就是两次调用。

实测理由：一个想在编译器 `nl.py` 里找匹配规则的编辑者读了约 1,000 行，然后用一份文件转储作答。它真正需要的那些
事实离它只有三次工具调用。**阅读预算：每次读取 ≤200 行，而且读 TTL 和 profile——不读引擎。**

## 用户说业务的话，你说声明的话

提指标的人懂业务，不懂 schema：这个数字叫什么、它回答什么问题、用文字怎么算出来、业务的一行是什么、范围是什么、
他们想按什么看它。他们永远不会去敲 TTL、列名或 JOIN——也不该有这个负担。

[references/user-intake.md](references/user-intake.md) 是面板摆在他们面前的采集表单，也是把它翻成声明的契约：哪个
答案变成 `:grain`、哪个变成 `:where`、哪个变成 `:formula`/`:numerator`，以及留空意味着什么。**留空是一个问题，
不是一个默认值**——粒度、范围和阈值决定了这个数字*意味着*什么，所以要用业务的话去问他们（"按每一趟车算，还是按
每一家门店算？"），而不是挑一个方便的。

回报的时候也用业务的话：这个数字现在是什么、它回答的那句话、它必须碰到哪些对象、那个值、证明它的独立路径，以及还
有什么必须由人来决定。永远不要把一堆声明贴到用户脸上去当回答。

## 这个循环——永远按这个顺序

1. **打开一个副本。** `ontology_open(ontology_key="logistics")` 把已安装的本体复制到 `work/logistics/`。仓库
   不是你可以改的，副本才是。
2. **动之前先读。** 读 profile（`*_settings.json`）和你要改的那个文件。它的命名空间、`ontology_dir`、
   `overlay`、`guard` 限制和 `features` 决定什么是合法的。
3. **给这次变更分类**——它归哪个文件（见下表）。改错文件，是一次修改"生效了"却什么都没变的最常见方式。
4. **只改那个文件**，改到最小。
5. **验证数字**，而不是验证文件：编译它、在护栏下跑它，然后对着**独立手写的第二条 SQL 路径**核对。跑得起来的
   指标不等于正确的指标。
6. **发布**：`ontology_publish(ontology_key=…, source_dir="work/<key>", include=…)`。它对着一个暂存副本重跑
   整套检查，遇到一个**新的**拒绝或一道失败的门禁就拒绝发布。读一读返回给你的报告。
7. **报告**暂存 id、那些数字、门禁，并按名报告哪些是 NOT RUN。应用是人的一次点击（`ontology_editor`）；永远不要
   因为你暂存过就宣称本体已经生效。

## 哪个文件拥有哪次变更

| 需求 | 文件 | 改动 |
|---|---|---|
| "这个数字应该是 X，不是 Y" | `ontology/02-meaning.ttl` | 那条公理：哪些行在范围内（`owl:intersectionOf` / `unionOf` / `:hasValue`）。绝不是往 SQL 里手打一个 `WHERE` |
| "按区域 / 按月分组" | `ontology/02-meaning.ttl`（+ overlay 的 `:groupBy`） | 该维度必须是已声明的属性；如果不是，先在 `01-structure.ttl` 里声明它 |
| "按站点计数，不按行程" | overlay 的 `:grain` / `:universe` | 是粒度让一个数字可数；改它就会改到每一个消费方 |
| "用平均而不是求和"、"要一个比率"、"按百分比显示" | overlay：`:aggregate`、`:numerator`/`:denominator`、`:scale` | 比率要声明它的两个指标，绝不手写 `sum(a)/sum(b)` |
| "只要最近 30 天" | 在**已声明**的带窗口类上写 overlay `:where` | 窗口是一个定义，不是一个 SQL 过滤器 |
| "这一列的含义不是这个" | `ontology/01-structure.ttl` | `rdfs:label`、`:physicalColumn`、`:businessDescription`；重命名必须保持属性在每个类里唯一 |
| "这些词 / 这些问题 / 别名不对" | profile：`samples`、`aliases`、标签 | 每个样例必须答出来，或者**按名**拒绝 |
| "教程不对 / 太薄" | `tutorial.json` | 每个 `items` 名字都必须已声明；必须有一个指标步真跑出数；必须有一个拒绝步 |
| "它拒绝太多 / 这个应该被允许" | profile 的 `guard` | 按真实的数据范围决定是拒绝还是收窄；已声明的指标**永不**加窗口 |
| "它返回空 / 返回全部" | 内省，而不是声明 | 改含义之前先查数据范围和连接路径 |

## 动手之前：缺的是词，还是声明？

一个没被回答的问题有三种原因，只有第三种需要新声明：

1. **词**——profile 的 `aliases` 缺一个同义词（`车` → `vehicle`，`趟次` → `trip`）；
2. **标签**——`rdfs:label` 不是人们会打的短语（它是*标签*，不是描述：当指标按站点计数时写 `站点准时率`，而不是
   `准时率`）；
3. **声明**——指标不存在，或者它的 `:where`/`:grain`/`:formula` 不存在。

先查 1 和 2。缺一个同义词不等于缺一个指标，而为了修一个措辞问题去加一条声明，正是两个指标开始抢同一个问题的方式。

## 你必须拒绝做的事

说不，并说出原因——这些是会毁掉本体价值的那类请求：

- 背后没有任何规则，就要**"把这个数字改成 X"**。数字是一个定义的产出。去问哪些行在范围内、按什么粒度、用哪个
  阈值。
- **发明一个阈值或一个粒度。**（`atRiskDriver`、"好线路"、"最近"）——去问。这就是为什么每次构建里总有些指标是
  *按名拒绝*的：在业务做出决定之前，拒绝就是诚实的答案。
- 为一个指标**手写 SQL**，或者加一条绕过编译器的代码路径。编译器是 SQL 的唯一来源。
- **新增一个没有 `:grain` 的指标**，然后再"让它跑起来"——编译器的拒绝是对的。
- **写一个分组比率。**带 `:groupBy` 的 `:aggregate "ratio_of_sums"` 会被按名拒绝（*"sum/count/avg/min/max
  are"*）：把它拆成一个未分组的跨粒度比率，或者一个可分组的可加指标，并说明你选的是哪个。
- **放宽 `features` 或任何护栏限制，只为让一个数字通过。**宁可把问题收窄，或者把拒绝报上去。
- **直接改已安装的本体**（仓库路径）。应用是一个带角色和确认的人工决定；直接写会跳过每一道门禁，什么也不留在
  审计轨迹里。

## 你自己就能跑的验证

仓库里的编译器就是工作台用的那一个。把 `PY` 设成一个带 `psycopg2` + `rdflib` 的解释器（本应用自己的解释器），
然后跑本技能里的单指标检查器：

```bash
# compile everything, refusing by name (no database needed)
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json

# one metric: compiled SQL + the number under the guardrails
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json --metric tripCount --sql

# and against your own hand-written route (the only proof that counts)
$PY scripts/check_metric.py --profile ... --metric totalRevenue \
    --independent "select sum(revenue) from trips"
```

`--independent` 跑的是**你**写的一条查询，走另一种代数路径，然后做比较。两者对不上，说明定义和路径对不上——发布
之前先搞清楚业务指的是哪一个。永远不要把你从编译器拿到的值贴进 `--truth`。

还要检查这次修改是否咬在该咬的地方：

- 你碰过的指标仍然编译，而**你没碰过的那些拒绝仍然拒绝**，且措辞一模一样（一次悄悄让某个东西不再被拒绝的重命名，
  就是一个 bug）；
- 如果这次修改收窄了行，数字就必须**动**——数字一点没变的改动，通常意味着你改了一条没人读的声明；
- 如果你改了指标名，每个消费方都跟着动了：样例、教程的 `items`、别名，以及任何引用过它的 `:numerator`/
  `:denominator`。

## 发布门禁是最后一道门禁

`ontology_publish` 把这次修改的拒绝与已安装的拒绝做对比：

- **出现新拒绝 → 发布被拒绝。** 一个不再编译的指标，就是一个从报表里悄悄消失的数字。
- **沿用的拒绝 → 放行。** 早就被拒绝的东西属于既有待办。
- **NOT RUN 的门禁按名打印。**"这个 profile 没有真值图"不是"已验证"。

按这个形状读返回的报告，并把它放进你的回答里：

```
compile: 21 of 24 metric(s) compiled, 3 refused by name
  REFUSED atRiskDrivers: :AtRiskDriver has no owl::equivalentClass axiom — nothing to compile
carried refusals (already refused in the installed ontology): atRiskDrivers, …
gates: PASS
gates NOT RUN (named, not passed): [NOT RUN] R2 …
```

## 做完的含义

- 这次改动在 `work/<key>/` 里的**一个**声明文件里，人能读懂；
- 指标的数字已经对着**第二条**路径核对过（或者这项检查被报为 NOT RUN）；
- 存在一次暂存发布，且它的报告里没有新拒绝、没有失败的门禁；
- 你的回答点名了还有什么是被拒绝的、什么是 NOT RUN 的，以及**应用是人的那次点击**；
- 工作台上的数字只在那次点击**之后**才动——把这点说出来，而不是宣称成功。

## 前提条件（由宿主提供，不由本技能提供）

| 能力 | 为什么 |
|---|---|
| **`ontology_open`** | 把 `ontologies/<key>/` 复制到 `work/<key>/`——已安装的事实不在你的工作区里，用 shell 拷仓库会破坏边界，也不留任何痕迹 |
| **`ontology_publish`** | 唯一的回程通道：暂存、对着副本重跑编译 + 门禁、遇到新拒绝就拒绝、永不安装 |
| **文件读写** | 你改的是副本；一次变更一个文件 |
| **shell 执行** | `scripts/check_metric.py` 就是本地的验证回路 |
| **一个带 `psycopg2` + `rdflib` 的 Python** | 检查器要 import 本应用的 `sqlgen`/`guard`；仓库自己的 venv 是 `<the app's own .venv: the interpreter that runs the backend>` |

没有 `ontology_open`/`ontology_publish`，这次修改就是 NOT RUN：说出来并把文件夹交出去，而不是手写进已安装的本体。
