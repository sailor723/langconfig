# ABC 冷链物流（logistics）语义层 — 阶段 6–8 验收记录

数据库：`abc_coldchain` @ 127.0.0.1:5432（user `weiping`）
编译器：`backend/features/ontology/compiler/sqlgen.py` + `guard.py`（本应用内，只读引用，不手检）
产物：`logistics_settings.json`、`ontology/01-structure.ttl`、`ontology/02-meaning.ttl`、`metrics_ext.ttl`、`tutorial.json`

---

## 阶段 6 — 用真正的编译器把所有指标编一遍

命令：`python3` 载入 `sqlgen.load()` 后对 `sqlgen.metrics(g)` 逐个 `compile_metric()`（原始输出见 `generated/compile_all.txt`）。

图规模：846 三元组 / 24 类。结果：

| 结果 | 数量 | 指标 |
|---|---|---|
| COMPILES | 20 | tripCount, stopCount, complaintCount, vehicleCount, onTimeStops, tempExcursionStops, overloadedTrips, permitVehicles, unjudgedComplaints, basketsMissingCount, damagedBoxCount, totalClaimAmount, totalRevenue, overloadRate, stopOnTimeRate, permitCoverage, complaintsPer1kStops, damagePer1kStops, damagedBoxesByStoreZone, overloadsByRouteVersion |
| REFUSES（按名） | 3 | `atRiskDrivers`、`plannedStopsVisited`、`driverRecentOnTimeRate` |

三个拒绝都不是"绕过去"，而是**缺业务口径**，编译器按名说清缺什么：

- `atRiskDrivers` — `:AtRiskDriver has no owl:equivalentClass axiom — nothing to compile`（"高风险"的阈值是业务决定，库里没有）。
- `plannedStopsVisited` — `:PlannedStopVisited has no owl:equivalentClass axiom`（"已访"到底指签到、到店还是签收，库里三种都有，选哪个是业务决定）。
- `driverRecentOnTimeRate` — `class :DriverWindow declares no :physicalTable`（`driver_stats` 每行一个司机、窗口恒为 30 天，没有"近 30 天"这个颗粒；要它就得先有窗口表）。

编译期一处发现（**报出来，不掩盖**）：`_compile_grouped_metric` 对公式列是先按 grain 自己的列解析（grain-first shadow），`class_columns()` 又只读一个 `rdfs:domain`，所以"一列挂到第二个类"这种重复列**编译器不会在编译期拒绝**——详见下面 M2。

## 阶段 7 — 护栏：窗口还是拒绝，由内省到的日期范围决定

内省（`now()` = 2026-11-07）：

| 表 | 列 | 范围 | 判断 |
|---|---|---|---|
| trips | trip_date (date) | 2026-08-08 .. 2026-11-05 | 最晚一条距今 **2 天** → 近期数据 |
| complaints | opened_at (timestamptz) | 全部 2026-11-05 09:00 | 近期 |
| telemetry | ts (timestamptz) | 2026-11-03 06:00 .. 08:45 | 近期 |
| stops | — | 无自有时间列（时间在 trips.trip_date，隔 trip_id） | 只进 large_tables，不注入窗口 |

行数（`pg_stat_user_tables`）：stops 51,210 / telemetry 12,144 / complaints 6,876 / trips 4,050 / route_stops 1,138 / stores 800 / handlers 420 / routes 90 / 60+60+60。

**决定：`default_window_days = 90`，不是 0。** 依据是内省到的日期范围：数据是近期的（最晚行程距今 2 天，整段历史 2026-08-08..2026-11-05 恰好 90 天），所以给 listing 兜一个能覆盖全部已加载数据的窗口，而不是拒绝。取 90 不取 30：30 天会切掉 8 月三分之二的行程，而兜底窗口不该在用户没设窗口时悄悄丢数据。数据哪天变历史（最晚 `trip_date` 距今 > 90 天），这条必须改成 0 —— 让无窗口的 listing **按名拒绝**，不是返回一张窄过的页。

`big_tables` 只收**同时有真时间列**的表：trips→trip_date、telemetry→ts、complaints→opened_at。stops 是最大表却没有自己的时间列，进 `large_tables`：算计划行数预算，不注入窗口（否则会拼出 `stops.trip_date`，SQL 直接报错）。

## 阶段 8 — 指标菜单、label、samples

- **菜单**：23 个指标，每个都有 `rdfs:label`（中文，就是用户会打的词："行程数""准时率""按门店区域看破损箱数"…），零缺失。
- **aliases**（per-profile，不全局）：线路→route、趟次/趟→trip、站点→stop、门店/店→store、司机/师傅→driver、车辆→vehicle、客诉/投诉→complaint、片区/区域→zone、装卸工/临时工→handler、版本→version、破损/货损→damaged、超载→overload、通行证/路权→permit、温度→temp。
- **samples**：15 条（契约 8–15），全部用 label 原词，其中 5 条按名拒绝（含两个概念缺公理、一个颗粒不存在）。
- **tutorial.json**：9 步（6–10），先颗粒、再定义、再指标、最后拒绝与护栏；14 个指标步骤、10 个定义步骤、3 个拒绝步骤全部真跑过。

---

## 门（14/14 PASS，逐条数字见 `generated/gates_output.txt`）

| 门 | 结果 |
|---|---|
| ontology.compile | 23 declared → 20 compile, 3 refuse by name |
| ontology.truth | 20/20 编译指标 = 独立手写 SQL 路由；3 个按名拒绝无需路由 |
| ontology.mutations | 4/4 RED：M1 删 :references（编译期拒绝）、M2 重复列（运行期被 PostgreSQL 拒绝）、M3 删 :grain（编译期拒绝）、M4 公式列拼错（编译期拒绝） |
| ontology.refusals | 3 条，全部由图上生成，非手写 |
| guard.page_cap | stops listing 51,210 行 → 返回 500 行，LIMIT 注入 True |
| guard.time_bound | trips listing 注入 trip_date >= now()-90 days；window_days=0 时按名拒绝；stops 无窗口 |
| guard.plan_budget | stops×telemetry 计划 ≈ 6.2 亿行 > 5,000,000 → 拒绝 |
| guard.metric_not_windowed | tripCount 值 4050 在 max_rows=500 与 max_rows=1 下都一样；只加了页帽，没注入窗口 |
| reasoning.samples | 15 条：12 答、3 按名拒绝、0 条无名拒绝（修正后，见下方「两处自查发现的错」） |
| reasoning.consistent | 1101 条蕴含；四个子类均 < FailedDelivery；不相交类共 0 行；FailedDelivery 7,297 = 四成员并集 7,297 |
| tutorial.steps_resolve | 9 步 / 37 个 items（11 对象 + 9 定义 + 14 指标 + 3 拒绝），source=profile，unresolved=none |
| tutorial.metric_runs | 14/14 ok:true，带值与计划行数（tripCount=4050、stopCount=51210、complaintCount=6876） |
| tutorial.definition_rows | 9/9 定义项选到非零行（OnTimeStop=47,920、LateStop=3,290、TempExcursionStop=1,930、UnjudgedComplaint=3,167） |
| tutorial.has_refusal | 3/3 拒绝步骤真的拒绝 |

未运行的门：无（全部在本机跑过）。

## 需要业务拍板的两处（我没有猜）

1. "高风险司机"的阈值（晚点率 > 20%？投诉数 > N？）——没有依据，`atRiskDrivers` 保持按名拒绝。
2. "计划门店已访"以哪个事件为准（签到 / 到店 / 签收）——`plannedStopsVisited` 保持按名拒绝。

---

## 教程逐个 items 自查（`GET /api/tutorial/steps` → 每个 items[] 打到对应端点）

证据文件：`generated/tutorial_selfcheck.txt`。

| 步骤类型 | items | 端点 | 结果 |
|---|---|---|---|
| objects（11） | Trip … Complaint | 查图（definition 端点只服务定义类，不服务对象） | 11/11 有 `:physicalTable` + `:primaryKey` |
| definitions（9） | 6 + 3 | `GET /api/tutorial/definition?class=` | 9/9 `ok:true` 且 `rows > 0` |
| metrics（14） | 数字与比率 | `GET /api/tutorial/run?metric=` | 14/14 `ok:true`，带 `value` 与 `plan_rows` |
| refusals（3） | 三个答不了的词 | `GET /api/tutorial/run?metric=` | 3/3 按名拒绝 |

`/api/tutorial/steps` 自己报 `source=profile`——教程是照 profile 渲染的，不是另写的一份。

## 两处自查发现的错（已修，不是绕过）

**1. 两个本来答得了的问题被能力图按名拒绝。** `:UnjudgedComplaint`、`:OverloadedTrip` 只写了
`:physicalPredicate`，没写基数对象，`concept_base_class()` 拿不到落地表，`nl` 于是报
"filters :UnjudgedComplaint, but that class reaches no physical table"。编译器本身没这个毛病
（`count(*) FROM complaints WHERE liability IS NULL` 编得出来、3,167 行对得上），所以这是
推理通道与编译器口径不一致，不是数据问题。修法是在 `ontology/02-meaning.ttl` 补两句真实成立的
`rdfs:subClassOf`（未判定投诉就是投诉行、超载行程就是行程行，同 `:FailedDelivery` 的写法）。
修完两条问题都 `ok:true`，两条指标的 SQL、值（3,167 / 1,489）一字未变，samples 从 10 答 5 拒
变成 12 答 3 拒。**我没有把闸门的判定放宽，是把图改对。**

**2. `tutorial.definition_rows` 曾报 10/10，而 API 里定义项只有 9 个。** 数字对不上就是对不上，
现已按 items 实数重算为 9/9，与端点逐条一一对应。

## 两条端点行为，写在这里免得被当成指标错

- **分组指标在 `run` 端点里 `value` 是第一个分组键，不是数字**（`damagedBoxesByStoreZone`
  返回 `value="core"`、`overloadsByRouteVersion` 返回 `value="v2"`）。这是端点给标量指标设计的返回形状，分组结果的行在
  SQL 里而不在 `value` 里。真值由 `ontology.truth` 的独立 SQL 路由核过，没靠这个字段。
- **`plan_rows` 只统计 budgeted 表**（`big_tables` ∪ `large_tables`）。`vehicleCount=60`
  的 `plan_rows=0` 不是"计划为空"，是这条 SQL 没碰大表；`vehicles` 只有 60 行，本来就该放过。

