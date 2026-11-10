---
name: "build-ontology-dashboard（搭建本体仪表盘）"
lang: zh
translated: machine
source: backend/skills/en-originals/build-ontology-dashboard/SKILL.md
description: >-
  本体需要一个仪表盘时使用——一份声明（dashboard.json）说明每个面板展示哪一个编译出的指标，一段只引用编译数字的
  开场评估，需要排版能力的图表（sankey/bubble/treemap），以及在服务端重新编译的交叉筛选；本技能走的是让看板保持
  诚实的那个顺序（声明 → 编译 → 护栏 → 门禁 → 之后才轮到页面），并且拒绝让面板发明一个本体没有声明的数字
tags: [ontology, dashboard, semantic-layer, metrics, sql, gating]
triggers:
  - "被要求在某个本体之上搭一个仪表盘 / 看板 / 经营看板，或对它做扩展时"
  - "仪表盘上出现了一个没人能追溯到声明的数字时"
  - "面板之间必须交叉筛选、而这个筛选不可能是浏览器里的猜测时"
  - "一段开场评估不能偏离它所谈论的那些数字时"
version: 1.0
author: weiping

# 把技能对准一个本体。仪表盘就是 `<profile dir>/dashboard.json`；不需要别的信息就能知道它在哪，
# 所以文件缺失本身就是一个真实的答案（"这个本体没有仪表盘"）。
params:
  ontology_key:
    label: 本体
    description: ontologies/ 下正在搭建仪表盘的那个文件夹（例如 logistics）
    required: true
  profile_file:
    label: profile 文件名
    description: 该文件夹里的工作台 profile
    required: false
    default: "{ontology_key}_settings.json"
---

# 搭建本体仪表盘

仪表盘是一份**声明**，不是一页查询。`dashboard.json` 说明每个面板展示*哪一个编译出的指标*、*按什么切*、一个未填的
空洞代价是什么，以及一个被筛选过的视图允许怎样不同。页面负责画，编译器负责答。中间没有任何东西计算数字。

本技能就是让这件事一直成立的那个顺序，外加让每一步真的咬得住的门禁。

## 0. 必须事先成立的前提

仪表盘骑在本体**必须声明**的能力之上。写面板之前先检查这些——每缺一项都会变成一张拒绝卡片，这没问题，但分得清
缺的是哪一项，就是一份设计与一堆空洞的区别：

| 能力 | 声明 | 缺席时的拒绝 |
|---|---|---|
| 每个分组的比率 | `:aggregate "ratio_of_sums"` + `:groupBy`，**两侧同一粒度** | *"grouped ratio compiles only when both sides share the grain"* |
| 一条时间序列 | `:timeBucket "week"` + 该粒度自己的 `:timeColumn` | *"declares :timeBucket … but :Stop declares no :timeColumn"* |
| 一个存在性事实 | `owl:someValuesFrom` 限制 + 反向链接 | *"has no owl:equivalentClass axiom"* |
| 交叉筛选 | 该维度必须是某个已声明指标的 `:groupBy` | *"cannot filter :Trip by :storeZone"* |

问编译器，不要去读源码：`python backend/features/ontology/compiler/run_dashboard.py --profile … --metric <name>`。

## 1. 用已声明的东西搭骨架（绝不按你的愿望搭）

```bash
PY=<the app's own .venv: the interpreter that runs the backend>
cd <ontology repo>/retail_graph
$PY ../backend/skills/builtin/build-ontology-dashboard/scripts/scaffold_dashboard.py \
    --profile ../ontologies/logistics/logistics_settings.json --out /tmp/dashboard.json
```

它产出的是基于编译后图谱的起步版 `dashboard.json`：KPI 来自未分组的指标，每个分组指标一个面板、形状由声明决定
（1 个键 → series/ranked/composition，2 个键 → matrix），还有一份 `holes` 清单，列出每一个拒绝的指标**及其必须
拒绝的原因**。它不编造阈值、句子或事件标记——它原样打印它留给你的是些什么。

读一遍骨架，然后删掉它的绝大部分。一个 30 个面板的仪表盘是本体的截图，不是看板：留下能回答业务问题的那 8–14 个，
其余放到下钻后面。

## 2. 开场评估是最难的部分

`briefing` 是**不含手打数字**的文字：每个值都是 `{metric}`（标量）、`{metric:key}`（一行分组结果）或
`{metric:key#key}`（回显那个键，用于含数字的车牌 / 编码）。门禁 `D7` 会剥掉占位符，剩下任何数字就失败——实测：
第一版手打了"50 条压成 40 条"，在一句讲每线路站点数的话里报了个行程数，修法是去*声明* `routeCountByVersion` 和
`stopsPerRouteByVersion`，而不是改写那句话。

`policy` 存放把描述变成判断的那些阈值。每个阈值在被人确认之前都带 `assumed: true`，界面上标为假设。判定由门禁从
指标值重新算——返回体里自带的 `breached` 标记从不被采信。

`cannot_see` 是评估的一部分。数据的病态就写在这里（恒定时间戳、未记录的决策、缺失的财务字段），而不是被悄悄
平均掉。

## 3. 面板：挑能显示这个发现的最小种类

十种面板种类、每种各需要哪些字段、门禁检查什么，见 `references/chart-kinds.md`。让面板保持诚实的规则：

- **色带 / 单元 / 圆点都是一个已声明的值。** Sankey 的一条连线是 `metric:key`，不是两个面板相加。
- **空洞本身就是一个面板。** 拒绝的指标要么成为一张点名缺失声明的拒绝卡片，要么成为一条已声明的 `holes` 条目，
  写明它预期的那个拒绝（`D4` 会让一个开始作答的空洞失败）。
- **NULL 分组也是一个分组。** 未判定的责任是一个标着"未判定"的单元，绝不是 0，也绝不丢掉。
- **事件标记需要一条时间轴**（`D6`），放在分类轴上的事件标记是拿因果撒谎。

## 4. 交叉筛选：重新编译，绝不重新加权

`?filter=<dimension>:<value>` 交给运行器，运行器把它转给编译器（`sqlgen.apply_dimension_filters`）。筛选以粒度
自己名字的派生表形式施加，所以**每一处** `FROM grain` 都被收窄——这是双子查询 RATIO 两侧同时被筛的唯一办法。
值必须是声明提供过的值，否则运行器以退出码 2 结束并给出允许清单：不然 `routeVersion=v9` 会自信地答一个 `0`。

接下来看板必须显示什么，以及 `F1` 查什么：

| 规则 | 为什么 | 门禁 |
|---|---|---|
| 每个 `emit_filter.dimension` 都是某个已声明指标的 `:groupBy` | 值集合是一份声明，不是界面上的清单 | `F1a` |
| 对 v 求和：Σ(metric \| dim=v) == 未筛的指标 | 筛子只落到了分子上 | `F1b` |
| 筛到 v2 的 `overloadRate` == `overloadRateByRouteVersion` 里 v2 那一行 | 唯一能同时证明两侧的那个检查 | `F1c` |
| 够不到的维度**按名**拒绝 | 按门店区域切不可能改变行程数 | `F1d` |
| 未知的值由运行器拒绝 | 一声不响的 0 是最差的答案 | `F1e` |

当一个视图的主题就是那条缺失的记录（例如一个衡量"没有记录派车决策"的面板），它要声明 `filter_not_applicable`，
并带上不适用筛选的徽标：一块内容没被筛时，被筛过的看板绝不能看起来整块都被筛过。

## 5. 先过门禁，再展示

```bash
$PY check_dashboard.py --profile ../ontologies/logistics/logistics_settings.json
$PY check_dashboard.py --profile … 2>&1 | grep -E 'FAIL|checks,'
```

`D0`–`D9` + `F1`：物流看板上一共 196 项检查（见 `references/gates.md`）。两种失败形状可以证明它咬得住——改动一条
声明，看对应那一族变红：

- 把一个面板指向拼错的指标 → `D0` 会点名那个面板和那个指标；
- 把 `FILTER (WHERE …)` 从分组比率的路径里删掉 → `D3` 的加权恒等式**和** `D5` 的独立 SQL 一起变红。

不会失败的门禁只是装饰。加一条检查，就要加一条能让它失败的改动。

## 6. 运行器返回什么，页面可以拿它做什么

`GET /api/ontology/<key>/dashboard/panels[?filter=dim:value]` → 那份声明，外加每个指标的 `status`、`label`、
`unit`、`keys`、`rows`、`sql`、`guard_notes`、`plan_rows`。页面可以格式化、可以排版；不可以加、不可以除、不可以
加权。它唯一挨着算术的那件事——把不匹配选中项的行藏起来——是排版，而且它会说明这一点。

## 反模式（这些全都是这里真出过的 bug）

- 一个把两个面板相加凑成一条色带的图（破坏 `D8` 的守恒）；
- 一个"最差的 20 台车"清单，指标编译成 `ORDER BY … DESC` 却缺 `client_sort: true`（`D2`），于是看板展示的是
  最好的 20 台；
- 把恒定列上的直方图画成趋势（一个桶就是结论，把结论说出来）；
- 在浏览器里"只为可见面板"施加的筛选；
- 一个悄悄丢掉指标被拒那个面板的仪表盘。

## 参考资料

- `references/declaration.md` —— `dashboard.json` 的契约，逐键讲，并说明每个键为什么存在。
- `references/chart-kinds.md` —— 十种面板种类，以及每种需要什么。
- `references/gates.md` —— `D0`–`D9` + `F1`，每个怎么咬住，以及证明它的那些改动。
- `scripts/scaffold_dashboard.py` —— 从编译后图谱生成的起步声明。
- 可运行的例子：`ontologies/logistics/dashboard.json`（16 个面板，196 项检查的门禁）。
