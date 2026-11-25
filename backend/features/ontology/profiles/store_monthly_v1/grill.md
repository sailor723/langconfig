# grill — store_monthly_v1（门店经营看板）

状态：**前沿已空，全部决定已定。尚未实现任何东西。**（2026-11-25）

## 0. 我核实的事实（自己查的，没问用户）

| 事实 | 值 | 怎么查的 |
|---|---|---|
| 库 | `store_monthly_xlsx`（host 127.0.0.1:5433 user langconfig） | `psql -p 5433 -d store_monthly_xlsx` |
| 表 | `门店` 4 行 / `月度经营` 12 行 / `品类` 3 行 | `\dt` + `count(*)` |
| `月度经营` 列 | `月份` text、`门店编码` text、`营业额` bigint、`客流量` bigint、`客单价` numeric、`退货额` bigint | `\d+ "月度经营"` |
| `门店` 列 | `门店编码`、`门店名`、`城市`、`开业日期`(date)、`面积平米`(bigint) | `\d "门店"` |
| `品类` 列 | `品类编码`、`品类名`、`目标毛利率`(numeric) | `\d "品类"` |
| 品类切片 | **`月度经营` 里没有品类键** → 任何品类切片都做不出来 | 列清单 |
| `月份` 现值 | 2026-01 / 2026-02 / 2026-03，已是 YYYY-MM，无需转换 | `select distinct 月份` |
| 完整性 | 4 店 × 3 月 = 12 行齐全，**无缺月** | 12 = 4×3 |
| 除零风险 | `客流量` 无 0、无 NULL | 条件计数 = 0 |
| 退货边界 | `退货额` 无 NULL，12/12 行 < `营业额`（退货率 < 100%） | 条件计数 = 0 |
| 存量 `客单价` 列 | 与 `round(营业额/客流量,2)` **12/12 行一致** | 逐行比对 = 0 差异 |
| 本体 key | `store_monthly_v1` 已登记，编译产物 0 个 | `ontology_inspect` |
| 骨架 | profile 目录只有 `_brief.md` + `store_monthly_v1_settings.json`，**无 TTL 骨架** | `ls` profile dir |
| 端口 | 库在 5433；settings dsn 写 `${ONTOLOGY_DB_PORT:-5432}`，环境里 `ONTOLOGY_DB_PORT=5433` → 解析正确 | `psql -p 5432/5433` 对比（5432 上无 langconfig 角色） |

> `ontology_open` 这个工具在本 agent 上不存在；等价物是 profile 目录，里面没有 TTL 骨架，所以结构与含义两个文件由 `modeller` 从零写进 `work/store_monthly_v1/`。

## 1. 决定（用户 2026-11-25 一次性采纳全部推荐）

| # | 决定 | 用户的理由 / 我给的理由 |
|---|---|---|
| D1 | 四个数：营业额、客流量、客单价、退货率 | 看板范围 |
| D2 | 维度：按门店、按月份 | 看板范围 |
| D3 | 金额单位元、含税 | 金额口径 |
| D4 | 客单价 = 营业额 ÷ 客流量 | 定义 |
| D5 | 退货率 = 退货额 ÷ 营业额 | 定义 |
| D6 | 时间用月份 YYYY-MM | 时间口径 |
| D7 | 品类表只作参考、不上看板（事实表无品类键，天然成立） | 范围 |
| D8 | 不做写入能力（只读；settings `features.actions=false` 已一致） | 范围 |
| D9 | 只有 3 个月，不做同比 | 时间口径 |
| **D10（Q1）** | `营业额` = **毛销售额**，未扣退货的含税销售总额；`退货额` 为与营业额同口径的含税退货金额 | 退货率的分母必须是退货发生前的销售额，否则分母含义随退货波动 |
| **D11（Q2）** | **客单价以公式为准**（营业额÷客流量）；存量 `客单价` 列只作对账第二路径，不直接上板，不一致要报出 | 两个来源并存迟早给出两个数字 |
| **D12（Q3）** | 合计层**先加总再相除**（加权）：合计客单价 = 总营业额÷总客流量；合计退货率 = 总退货额÷总营业额。**不做比率算术平均** | 算术平均让小店与大店等权，谁也不认那个数 |
| **D13（Q4）** | **不设目标线/红绿灯**：不给客单价、退货率的红绿判定；`品类.目标毛利率` 不上板也不做阈值 | 阈值只能由业务给，编出来的红绿灯会被当成承诺 |
| **D14（Q5）** | 3 个月**平铺**、无「当期/完整月」概念；**允许月环比**（2 月对 1 月、3 月对 2 月）；**不做同比** | 无跨年数据；环比亚是同表内唯一能看的走向 |
| **D15（Q6）** | 看板 **3 块**：① 4 张 KPI 卡（营业额/客流量/客单价/退货率，3 个月合计）② 门店×月 矩阵（4×3）③ 月度趋势线（3 点）。不按城市分组、不做门店排名表 | 12 个数据点用 3 块就够，多出来的只是同一批数换排法 |
| **D16（Q7）** | 读者 = **门店店长 + 区域经理的月度经营复盘**；要回答「哪家店掉队了，掉在客流、客单价，还是退货」 | 12 行数据的自然用法是横向比店、纵向看月 |
| **D17（Q8）** | **没有**必须对上的现有报表或官方口径文档；本表即口径来源，不承诺与外部报表逐分对齐 | 凭空承诺对账，只会变成一个查不动的差异 |

## 2. 由上述决定直接推出的实现约束（给专家，不需再问用户）

1. **`客单价` 与 `退货率` 是编译出来的比率，不是表里的列**（D4/D5/D11）。存量 `客单价` 列在 `02-meaning.ttl` 里只能作为对账/样例的第二路径提及，不得成为指标口径来源。
2. **比率在聚合上不可加**（D12）：门店合计、多月合计必须重新按 ∑分子/∑分母 编译，不能 sum 比率。这条要落到指标声明里，让编译器生成 `sum(a)/sum(b)` 而不是 `sum(ratio)`。
3. **无目标、无阈值**（D13）：护栏里不得出现基于业务阈值的红绿灯；护栏只允许质量类（行数、除零、退货率 >100%、NULL）。
4. **环比可用、同比不可**（D14）：不要声明任何需要上年同期的指标；时间维度就是 text 的 YYYY-MM，没有日期列。
5. **粒度**：`月度经营` 的**一行 = 一个门店的一个月**，主键（门店编码, 月份）；已证实 4×3=12 行无重复无缺月。
6. **只读**（D8）：不声明任何 action。

## 3. 有意未定（现在不定，且说明什么会让我改主意）

| 未定项 | 为什么现在能不定 | 什么会让我改主意 |
|---|---|---|
| 门店维度的属性（城市、面积平米、开业日期）要不要进看板 | D15 只要 3 块板，城市分组已被排除；这些列是参考信息 | 用户说「按城市看」或「要坪效」——坪效需要 面积平米，且要新增一个指标定义 |
| 是否需要「退货额」本身作为独立 KPI（而非只在退货率里） | D1 只点了四个数 | 用户要在板上直接看退货金额 |
| 客流量与营业额的计量单位之外的口径（如是否含线上单） | 表里没有渠道列，无法区分 | 数据补充渠道列 |
| 环比是否要做成看板上的显式面板 | D14 允许但 D15 只给了 3 块板，环比作为趋势线的读法 | 用户要求显式的「环比 %」数字列 |
| `品类.目标毛利率` 的用途 | D7 + D13 双重排除 | 用户要给品类毛利达标度做看板——需先有品类键的事实表 |

## 4. 下一格

`modeller`：写 `work/store_monthly_v1/01-structure.ttl`（S1 结构/粒度）与 `02-meaning.ttl`（S2 含义/口径/单位）。

## 5. 执行进度

### S1 + S2 已交付（modeller）

- 产物：`work/store_monthly_v1/01-structure.ttl`（115 三元组）、`02-meaning.ttl`（33 三元组）、`NOTES.md`。
- **我自己复核过的**（不是转述 modeller）：
  - rdflib 解析两个文件均通过，115 / 33 三元组。
  - `grep -c :physicalColumn` = 14 = 全库 14 列（月度经营 6 + 门店 5 + 品类 3）→ 每列都被覆盖。
  - 3 个类、3 个 `:physicalTable`（月度经营/门店/品类）、3 个 `:primaryKey`（`门店编码, 月份` 复合键 / `门店编码` / `品类编码`）、1 个 `:references`（门店编码 → :Store），**没有品类关联** —— 与 D7 一致。
- **我复核不了、因此不当成已验证**：modeller 说 `check_structure.py` 28 checks 0 failed 全绿，但它跑的是它自己 workspace 里的一份 settings 副本，共享工作区里**没有**这份 settings，我也不能自己写 `*_settings.json`。用真实 profile settings 跑，门禁直接报 `no structure file: …/profiles/store_monthly_v1/ontology/01-structure.ttl`（TTL 不在那里）。所以「S1 门禁绿」目前**没有一条我能重放的命令作证**。

### 由此暴露的接线问题（不是用户要决定的，交给下一格修）

`store_monthly_v1_settings.json` 里 `ontology_dir = "ontology"`，而两个 TTL 现在躺在 `work/store_monthly_v1/` 根目录 —— 编译器只看 `<profile>/ontology/*.ttl`。本仓两种约定都在用：`meeting_v1` 是 `"."`（TTL 在根），`sunhing_v1` 是 `"ontology"`（TTL 在子目录）。修法：在 `work/store_monthly_v1/` 放一份 settings 副本、并把两个 TTL 放进 `work/store_monthly_v1/ontology/`，然后重跑 S1 门禁拿到可重放的绿行。**这件事由 metrics 格在写 S3 之前顺手做掉，不需要问用户。**

### 真需要人决定的（S4 才落定，先记账）

`settings.guard` 没有 `big_tables` / `default_window_days`，实测 `guard.config()` 会兜下 `compiler/guard.py` 里 retail 的 `DEFAULTS`（`big_tables={"orders":"placed_at"}`、`default_window_days=90`）。本库最大表 12 行、且**没有任何 timestamp 列**（唯一 date 列是 `门店.开业日期`），数据是固定历史窗口 2026-01~03 —— 正确取值应是 `big_tables` 空 且 `default_window_days: 0`（拒绝而非收窄，见 D14）。若 `check_ontology_generic` 的 G1a 断言「必须存在 big_tables」，那么这条会红，红的原因是一个**真实事实**（本库没有大表），不是缺陷。到 S4 我会带着实测数字把这一条摆给用户，不在这里替他决定。

### S3 + S4 + S5 已交付（metrics）—— 含我自己的重跑

产物：`metrics_ext.ttl`（167 三元组，14 个指标）、`samples.json`（15 条）、`store_monthly_v1_settings.json`（工作区副本）、`NOTES.md` 追加段。
`01-structure.ttl` / `02-meaning.ttl` **一字节未改**（cmp 相同）。

**我一个人重跑过、能重放的绿行**（命令见下）：

| 门 | 命令 | 结果 |
|---|---|---|
| S1 | `check_structure.py --profile work/store_monthly_v1/store_monthly_v1_settings.json` | 28 checks · 0 failed · green |
| S3 | `check_ontology_generic.py --family C` | ALL GATES PASS（compiled 14 · refused by name 0）|
| S5 | `check_samples.py` | ALL SAMPLES PASS（15 条，含 `route` 第二条 SQL 逐值比对）|
| S4 | `check_ontology_generic.py --family G` | **SOME GATES FAILED**：`[FAIL] G1a … no big_tables` |

- `ontology_inspect(source_dir="work/store_monthly_v1")`：compiled 14 / refused by name **0**。
- 比率编译形状实测：`((SELECT sum(退货额))::numeric) / NULLIF((SELECT sum(营业额)), 0)` = **sum/sum**，键值 0.02214268858648627389，notes `cross-grain ratio (:returnAmountTotal) / (:revenueTotal)` —— D12 的「先加总再相除」在编译产物里成立，不是声明里说说。
- 护栏实测 `guard.config()` = `{enabled, max_rows:500, default_window_days:0, statement_timeout_ms:8000, max_plan_rows:5000000, big_tables:{}, large_tables:[]}` —— 不再兜 retail 的 DEFAULTS，编译 SQL 只有 `+ LIMIT 500`，**没有任何窗口注入**。
- `features.actions=false`（D8）、`tutorial=true`。

**两条红线，都照实红着，没修**：

1. **G1a 红**（`no big_tables`）：本库最大表 12 行、全库无 timestamp 列。让这条变绿只有两条路，都不正当：编一张不存在的"大表"（护栏会往不存在的列注入窗口，每次读取都死），或改断言。**建议：接受这条红，在 gates 台账里登记为 known-red + 理由**，等用户拍。
2. **「品类毛利率」这条按名拒绝，实质弱于字面**：`samples.json` 记的 `refused_by_name` 是 `"I can answer about"` —— 那是 NL 的**通用菜单句**，不是一条点名理由。事实理由（品类表只有目标毛利率、无实际销售额与成本、事实表无品类键、join 不上）只写在 `_why` 里。门禁绿了，但用户点进去看到的是菜单，不是理由。**修法**：给 `:Category` 追加 `:refusalReason "…"` —— 那是结构层追加，metrics 格被"不改结构"约束住，没做。

**顺带被 metrics 抓到并修掉的一个真问题**（记一笔，因为它会静默答错）：分组比率的 label 原本带「（元/人次）」，导致「按门店看客单价」被解析成 `class Store→4 行`、「按月份看客单价」被解析成 `class StoreMonth→12 行` —— **自信的错答案**。去掉括号后解析到 `avgTicketByStore` / `avgTicketByMonth`。这条现在有样例守着。

**有意未定项（§3）一行没动**：退货额已编译但没做成 KPI 卡；坪效按名拒绝；按城市分组按名拒绝。

### D18（用户追加，覆盖 D15 的块数）—— 看板 4 个面板 + 教程 6 步
- **D18** 看板 **4 个面板**（D15 原写「3 块」，用户改为 4 个），仍然只按**门店**与**月份**切。
  D15 里点名的两块不撤：门店×月矩阵、月度趋势线。另两块由 board 在**已声明的指标里**选，
  不许为了凑第四个面板新造指标。
  KPI 卡（4 个数：营业额 / 客流量 / 客单价 / 退货率）走 `kpis`，**不占**这 4 个面板位。
- **D18b** 教程 `tutorial.json` **6 步**，其中**必有一步是拒绝**。
- **不变**：D13 无目标线/红绿灯（`policy` 里不许出现 assumed 阈值）；D7 品类不上板；
  品类毛利率进 `cannot_see` + S8 拒绝清单，**不做成 hole 面板**（`:Category` 是已声明的类，
  hole 面板要求类未声明，D4 会判它撒谎）。

### 仍未定（上一格提出，用户未答，原样挂着）
`:Category` 是否追加 `:refusalReason`。不追加则「品类毛利率」的拒绝在页面上是 NL 通用菜单句
（`I can answer about…`），事实理由只在 `samples.json` 的 `_why` 里。**不阻塞发布。**

### S6 + S7 + S8 已交付（board）—— 含我自己的重跑

产物：`dashboard.json`（4 面板 + 4 KPI 卡 + 6 条 cannot_see）、`tutorial.json`（6 步，第 6 步是拒绝）、`ontology.html`（109 KB）。
前四格产物 `01/02/metrics_ext.ttl/samples.json/store_monthly_v1_settings.json` cmp 全 SAME，**一字节未动**。

| 门 | 命令 | 结果 |
|---|---|---|
| S6 | `check_dashboard.py` | **39 checks, 1 failed** —— 唯一红：`FAIL D1 kpi returnRate carries a unit a reader can interpret (not a bare ratio) — unit='ratio'` |
| S7 | `--family T` | ALL GATES PASS |
| X | `--family X` | ALL GATES PASS（无机器路径/密码字面量）|
| P | `--family P` | ALL GATES PASS（4/4 类上页，14 编译 / 0 按名拒绝）|
| S5 | `check_samples.py` | ALL SAMPLES PASS（15 条）|
| S1 | `check_structure.py` | 28 checks · 0 failed · green |

4 个面板：`storeMonthRevenue`(matrix, `revenueTotalByStoreMonth`) / `monthTrend`(series, `revenueTotalByMonth`, 声明 `sort:"asc"`+`client_sort`) / `storeTicket`(ranked, `avgTicketByStore`) / `storeReturnRate`(ranked, `returnRateByStore`)。
KPI 卡 4 个 = D1 的四个数（不占面板位）。`policy: []` —— D13 无任何阈值。briefing 全是 `{metric}` 占位符，零手打数字。
`cannot_see` 6 条：品类毛利率 / 坪效 / 按城市 / 同比 / 退货额独立卡 / 时间窗。S8 拒绝清单落地于此 + `samples.json` 的 `_why`。

**D2 抓到的一个真问题**：`revenueTotalByMonth` 出厂行序是 **值 DESC**（2026-03 / 2026-01 / 2026-02），
不是时间序 —— 趋势线不声明 client_sort 就是乱序的 x 轴。已声明。

### ⚠ 发布前必须消掉的红（两条，都不是可以糊过去的）
1. **D1 / `returnRate` unit='ratio'**：门禁原文给了处方 —— `:scale "100.0"` + `:unit "percent"`。
   两个渲染器不一致是事实：`run_dashboard._fmt` 对 `ratio` 会 ×100 显示 `2.2%`（briefing 实测如此），
   而门禁作者在 v4/v5 实测过**卡片**把 `0.9459` 显示成 `0.95 %`（不乘 100）—— 同一份声明在卡片上差 100 倍。
   `percent`+scale 在两种渲染器下都读得对（`2.21` + 单位标签%），`ratio` 在卡片上读成 0.02%。**决定：改成 percent + scale 100.0。**
   代价：`samples.json` 里退货率（含两张分组）期望值 ×100，`metrics_ext.ttl` 三个比率指标改单位，board 重渲染。
2. **G1a `no big_tables`**（`--family G`）：本库最大表 12 行、无 timestamp 列，`big_tables` 只能为空；G1a 是裸
   `bool(big)` 断言，没有 opt-out。**未消，仍需你拍**（见下）。
