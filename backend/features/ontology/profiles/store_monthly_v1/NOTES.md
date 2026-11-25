# NOTES — store_monthly_v1（modeller 格：S1 结构 + S2 含义）

## 这一格读了什么
- `work/store_monthly_v1/grill.md`（用户决定 D1–D17、实现约束 §2、有意未定 §3）—— 已读，全部照做。
  注意：它不在 profile 目录里，而在 agent 工作目录 `work/store_monthly_v1/` 下。
- `_brief.md` / `store_monthly_v1_settings.json`（profile → `ontology_open` 的副本）：只有这两个文件，
  **profile 目录里没有 TTL 骨架**，S1/S2 从零写。`NOTES.md` 之前不存在（本格是第一格）。
- 格式参考 `work/meeting_v1/01-structure.ttl` / `02-meaning.ttl`（同名 profile 副本内容相同）。

## 产物在哪（两处，逐字节一致，`cmp` 校验过）
1. `work/store_monthly_v1/01-structure.ttl`、`work/store_monthly_v1/02-meaning.ttl` —— 任务指定的交付路径。
2. `<ontology_open 镜像>/work/store_monthly_v1/ontology/01-structure.ttl`、`…/02-meaning.ttl` ——
   因为 `settings.ontology_dir = "ontology"`，编译器只读 `<profile>/ontology/*.ttl`（`sqlgen.load()`），
   放在 profile 根目录的 TTL 不会被编译。第 2 份是为了让 `ontology_inspect(source_dir=…)` 与发布后的
   编译真的看到这两个文件。**改文件时两处都要同步**，或者先由人把 `ontology_dir` 改成 `"."`（见下）。

## 实测到的事实（都能重放；库 store_monthly_xlsx @ 127.0.0.1:5433 user langconfig）
- 三张表、全是 BASE TABLE、无视图：`select table_schema,table_name,table_type from information_schema.tables
  where table_schema not in ('pg_catalog','information_schema')` → 面板 3 行（品类/月度经营/门店）。
- 主键/唯一约束/索引：`pg_constraint`、`pg_indexes` 在 public 下 **0 行** → TTL 里的「主键」是数据事实。
- 粒度：`count(*)=12`、`count(distinct 门店编码)=4`、`count(distinct 月份)=3`、
  `count(distinct (门店编码,月份))=12` → 4×3 无重复无缺月。
- 列与类型：14 列（月度经营 6 / 门店 5 / 品类 3），类型只有 text/bigint/numeric/date，**没有 timestamp 列**。
- 无空值：`count(*) filter (where 任一列为 null)=0`（月度经营 6 列）。
- 客流量无 0（2700…5900）；退货额无 NULL、无负值（700…4300）、12/12 < 营业额。
- 存量 客单价 与 `round(营业额::numeric/客流量,2)` 12/12 一致（差异 0 行）。
- 门店外键完整性：`月度经营 left join 门店` 后 门店编码 is null 的行 = 0。
- 加权 vs 算术平均：`sum(营业额)/sum(客流量)=24.08` vs `avg(客单价)=23.48`；
  `sum(退货额)/sum(营业额)=0.0221`；单行退货率 0.0128…0.0273。
- **text 月份不能走日期路径（实测报错，不是推断）**：
  `select date_trunc('month',"月份") …` → `function date_trunc(unknown, text) does not exist`；
  `where "月份" >= now() - interval '90 days'` → `operator does not exist: text >= timestamp with time zone`；
  而 `where "月份" >= '2026-02'` 正常（返回 8 行）→ 字典序比较可用。
- 表体积：三张表各 16 kB（`pg_total_relation_size`），最大表就是 月度经营 12 行 → **本库没有 big table**。
- `guard.config()` 用本 profile 实测：`default_window_days=90`、`big_tables={"orders":"placed_at"}`
  —— 这是 `compiler/guard.py` 的 `DEFAULTS`（retail 的）兜下来的，因为 settings 的 guard 段没写这两项。
  本库没有 `orders` 表，所以今天不会命中；但这是真隐患，见 needs_human。
- `run_dashboard._fmt`：`unit == "ratio"` 会 ×100 显示成百分比，`unit == "money"` 显示 ¥ → 若 S3 同时写
  `:scale "100.0"`，看板会再乘一次。

## 校验结果（本格自查）
- `rdflib` 解析：01-structure 115 三元组、02-meaning 33 三元组，均通过。
- `gates/check_structure.py --profile <真实 settings>` → **28 checks · 0 failed · green**
  （S1a/S1b/S1b2/S1b3/S1c/S1d/S1e/S1f/S1g 全绿；S1f 不需要 `--allow-uncovered`，因为 品类 也建了类）。
- `gates/check_ontology_generic.py`：C0/C1a/C1b/C1c/C1d/C2b/C5a/C5b 全绿；唯一 FAIL 是
  **C2a "some metrics compile"（0 metrics）**—— 指标是 S3 的格子，不是本格的缺失；G1a（big_tables）FAIL
  属 settings，见 needs_human。
- `ontology_inspect(source_dir=…)` 问「2026 年 1 月每家门店的营业额是多少」→ 按名拒绝并指出缺一个
  metric（找到的是 :Store 类），说明 S1/S2 已被编译器读进来、NL 认识中文 label。

## 给下一格（S3 metrics）的交接（不是我要做的事，但读文件的人需要知道）
- 事实粒度 `:StoreMonth`，时间 `:month`，门店经 `:storeOf` 可达 `:Store`（`门店×月矩阵` 用 `:month` + `:store_name`）。
- 比率的正解是 `:aggregate "ratio_of_sums"` + `:numerator`/`:denominator` 两个同为 sum 的指标（D12），
  **不要** `sum(比率)`、也不要 `:additivity "non-additive"` + `:aggregate "sum"`（编译器会按名拒绝）。
- `:avg_ticket` / `:return_rate` 这两个 IRI 在 S2 里已带 label/unit/additivity/含义，S3 直接续写
  `:formula`/`:grain`/`:universe` 即可；`:universe` 用 `:AllStoreMonths`。
- 不要声明 `:timeBucket` 或 `:supportsSlot :TimeWindow`：`月份` 是 text，实测两条路径都会在数据库报类型错误；
  趋势线按 `:month` 分组即可。
- 每个 metric 要带 `:askedAs`，`:businessDescription` 里要带来源标记（`answers:`/`measured:`/`doc#`…），
  否则 check_ontology_generic 的 C5a/C5b 会红。

产物: work/store_monthly_v1/01-structure.ttl（115 三元组，check_structure 28/28 green）与 work/store_monthly_v1/02-meaning.ttl（33 三元组），另镜像到 ontology_open 副本的 ontology/ 子目录（settings.ontology_dir="ontology"，否则不参与编译）
未验证项: 品类表与月度经营之间「不存在可声明的关联」是按事实表 6 列与全库 14 列的类型/列清单推定的（无品类键）——若将来有人往库里加品类列，这条要重看；月度环比的「相邻两月相减」只验证了 text 的字典序比较可用（where "月份" >= '2026-02'），没写成指标（属 S3）
需要人决定: ① settings.ontology_dir="ontology" 与「TTL 写在 work 根目录」冲突：要么发布时把两个 TTL 放进 <profile>/ontology/，要么把 ontology_dir 改成 "."（settings 不是本格产物，我没改）；② settings.guard 缺 big_tables/default_window_days，实测会兜下 retail 的 DEFAULTS（big_tables={"orders":"placed_at"}、90 天）——本库最大表 12 行、无时间戳列，正确取值应是 big_tables 空 / default_window_days 0（并接受 check_ontology_generic G1a 因此 FAIL，因为那是「没有大表」这个事实）；③ grill §3 的未定项（退货额是否独立成 KPI、门店维度属性是否进看板、环比是否做成显式面板）在本层一律没声明，需用户点头才能加

---

# NOTES 追加 —— S3 指标层 + S4 护栏 + S5 样例（metrics 格）

## 这一格读了什么
- `grill.md` 全篇（D1–D17 照做；§2 实现约束；§3 有意未定项一律没补；§5 的接线问题按指示在写 S3 之前修掉）。
- 本文件上半部分（modeller 的实测与交接：哪个 IRI 已带 label/unit、比率必须 ratio_of_sums、不许 timeBucket）。
- `01-structure.ttl`（115 三元组）/ `02-meaning.ttl`（33 三元组）—— **一字节没改**（`cmp` 与上一格产物一致，见下）。
- 格式参考：`work/meeting_v1/metrics_ext.ttl`（形状）、`work/meeting_v1/samples.json`（route / refused_by_name 两种形状）、
  `meeting_v1_settings.json` 的 guard 与 **aliases** 段。
- `gates/check_samples.py` 的 docstring 与实现（知道它把 `expect.value`/`rows`/`route`/`refused_by_name`/`unresolved` 各当什么）。

## 产物（工作区 + 一份同步镜像，逐字节 `cmp` 校验）
1. `work/store_monthly_v1/metrics_ext.ttl` —— S3，**新文件**，14 个指标全部编译通过（0 个按名拒绝）。
2. `work/store_monthly_v1/store_monthly_v1_settings.json` —— **settings 副本**（不是注册 profile）：
   `ontology_dir` 由 `"ontology"` 改为 `"."`（TTL 在根目录，与 meeting_v1 同一约定）；`dsn.dbname` 仍是 `store_monthly_xlsx`；
   guard 段落定（见下）；**新增 aliases 段**（理由见「接线」）；samples 列表 = 闸门里那 15 条。
3. `work/store_monthly_v1/samples.json` —— S5，15 条（12 答 + 3 按名拒绝）。
4. 镜像：`outputs/users/1/work/store_monthly_v1/`（根 + `ontology/` 子目录）放同一批文件，`cmp` 全部 same，
   两份 settings 各自跑 `check_structure` / `check_samples` 都是绿 —— 交付的不是只在某个 agent 目录里才成立的东西。

## 门禁的最后一行（可重放；`PY=../.venv/bin/python`，cwd=`backend/`）
- `check_structure.py --profile <工作区 settings>` → **28 checks · 0 failed · green**（S1 仍绿，01/02 未动）。
- `check_ontology_generic.py --family C` → **ALL GATES PASS**（C0/C1a/C1b/C1c/C1d/C2a/C2b/C5a/C5b/C4a/C4b/C5c；compiled 14 · refused by name 0）。
- `check_ontology_generic.py --family G` → **SOME GATES FAILED**，唯一红行原文：
  `[FAIL] G1a the profile names its big tables — no big_tables`（G0 PASS、G1c PASS 空过）。
  这是**事实**不是缺陷：本库最大表 12 行 / 16 kB，且三张表都没有时间戳列 —— 没有一张表够得上「独立时间列的大表」，
  所以 `big_tables` 空，G1a 就必然红。**没有为了让 G1a 变绿去编一张表或一个列名**（那样护栏会往不存在的列注入窗口，每次读取都死）。
- `check_samples.py --profile <工作区 settings>` → **ALL SAMPLES PASS**（15 条；分组矩阵 12 组全对；四类拒绝全部按名拒绝）。
- 全量 `check_ontology_generic.py`（不带 --family）另见两条红：G1a（同上）与
  `P2 the profile has its own generated page — …/ontology.html is missing` —— P2 是 board 格的产物，本格被明确要求不写 `ontology.html`/`dashboard.json`/`tutorial.json`。

## 实测到的事实（都能重放；库 store_monthly_xlsx @127.0.0.1:5433 user langconfig）
**四个数（管线值 vs 我的第二条手写 SQL，两条路径同值）**
- 营业额 `SELECT sum(营业额) FROM 月度经营` = **1,271,300**（管线 value 同）。编译 SQL：`SELECT sum(营业额) AS revenue_total FROM 月度经营 LIMIT 500`。
- 客流量 = **52,800**；客单价 = `sum/sum` = **24.0776515151515152** 元/人次；
  退货率 = `sum(退货额)/sum(营业额)` = **0.02214268858648627389**。
- 反证 D12 非空洞：12 行 `avg(客单价)` = **23.480833** ≠ 合计口径 24.0777（`select round(sum(营业额)::numeric/sum(客流量),6), round(avg(客单价),6)`）。
- 编译形状（`ontology_inspect(metric=…)` 打印）：比率是
  `((SELECT sum(营业额))::numeric) / NULLIF((SELECT sum(客流量)),0)` —— 是 sum/sum，不是 sum(ratio)、不是算术平均。

**分组（`:groupBy` 编译出的 JOIN 与 GROUP BY，值与我手写 SQL 逐组相同）**
- 按门店名：营业额 374,800 / 256,700 / 457,500 / 182,300；客流量 15,100 / 12,200 / 16,600 / 8,900；
  客单价 24.8212 / 21.0410 / 27.5602 / 20.4831；退货率 0.023212 / 0.018309 / 0.026885 / 0.013439（新街口/五道口/天河城/春熙路）。
- 按月份：营业额 430,400 / 387,100 / 453,800；客流量 17,900 / 16,000 / 18,900；
  客单价 24.0447 / 24.1938 / 24.0106；退货率 0.022537 / 0.023250 / 0.020824。
- 双键矩阵（`:groupBy :month, :store_name`）：编译成
  `SELECT 月度经营.月份 …, 门店.门店名 …, sum(营业额) … GROUP BY 月份, 门店名`，12 组，键渲染成「2026-03 / 天河城店」。
- 分组比率仍是**组内** sum/sum：编译 SQL 里 `((sum(营业额))::numeric)/NULLIF((sum(客流量)),0) … GROUP BY`，
  notes 写的是 `grouped ratio: (:revenueTotal) / (:trafficTotal), both declared at :StoreMonth`。

**units / 缩放（自己实测，不是转述）**
- `run_dashboard.py:373` `_fmt`：`unit == "ratio"` → `v*100` + `%`；`unit == "money"` → `¥{v:,.2f}`；其它单位落到通用数字格式
  （整数原样、≥10 一位小数、≥1000 千分位）。所以 **退货率只写 `:unit "ratio"`、不写 `:scale`**：管线 value 是 0.02214（未乘 100，
  见 samples 的 `value == the hand SQL` 那两条），看板自己 ×100 → 2.2%。若同时写 `:scale "100.0"` 会乘两次、变成 221%。
- 客单价用 `:unit "money_per_visit"`（元/人次，自解释，不是裸 ratio）；客流量沿用 `:unit "count"`（与 02-meaning.ttl 的 `:traffic` 一致）。
  这两个单位在 `_fmt` 里没有专门分支 → 走通用数字格式（客单价渲染成 `24.1`、客流量 `52,800`，无单位后缀）。**这是实测的渲染行为，不是我改不了的缺陷**，见「需要人决定」。

**护栏相关（自己量过）**
- 表体积：`select relname, n_live_tup, pg_total_relation_size(relid) from pg_stat_user_tables` → 月度经营 12 / 品类 3 / 门店 4，三张都 16,384 B → **没有大表**。
- `guard.config()` 在本 profile 下实测：`{"enabled": true, "max_rows": 500, "default_window_days": 0, "statement_timeout_ms": 8000, "max_plan_rows": 5000000, "big_tables": {}, "large_tables": []}`
  —— 不再兜下 retail 的 `DEFAULTS`（`big_tables={"orders":"placed_at"}` / 90 天），这正是 S4 要修的那条隐患。
- 护栏没有往 SQL 里注入任何窗口：编译出来的都是 `… FROM 月度经营 LIMIT 500`（notes 只有 `+ LIMIT 500 (page capped)`），没有 WHERE。
- text 月份的两条日期路径仍是真错（本格自己重跑过，不是引用）：
  `date_trunc('month', "月份")` → `function date_trunc(unknown, text) does not exist`；
  `"月份" >= now() - interval '90 days'` → `operator does not exist: text >= timestamp with time zone`；
  而 `"月份" >= '2026-02'` 正常（8 行）→ 字典序可用，所以趋势线就是 `GROUP BY 月份`。

## 接线（这一步不做，写的东西不参与编译）
- **`ontology_dir`**：工作区 settings 副本改成 `"."`，TTL/overlay 都在 `work/store_monthly_v1/` 根目录；注册 profile 目录**没动**。
- **aliases 是必需的，不是装饰**（两条都是实测的拒绝，不是我猜的）：
  - 维度：没有 `"月份": "month"` / `"门店名": "store_name"` 时，问「按月份看退货率」被按名拒绝：
    `nothing declares a grouping by ['月份'] — … (grouped metrics: [('returnRateByMonth', ['month']), …])`。
    原因：`:month` 的 label / askedAs 都是中文，而匹配器只认属性名（`month` / `store_name`）。
  - 指标：没有 `"客流量": "trafficTotal"` 等时，「客流量是多少？」「客单价是多少？」「退货额是多少？」全部被
    `I can answer about: metrics […]` 拒绝（英文词表里没有这几个名词，2-gram 又匹配不上 `trafficTotal`）。加上 5 条指标别名后三条都答。
  - 反例（说明别名不是万灵）：`"按门店": "store_name"` 会让「按门店看客单价」退化成 `class Store → 4`，所以这条别名**没写**，只写 `门店名/各门店/各家门店/分门店`。
- **label 与 literal 匹配**：分组比率的 label 从「按门店看客单价（元/人次）」改成「按门店看客单价」——因为匹配器有一条「问题里逐字出现 label」
  的强规则（`label in question`），带括号单位的 label 享受不到它。实测改之前这两问分别被答成 `class Store → 4` 和 `class StoreMonth → 12`（自信的错答案），
  改之后解析到 `avgTicketByStore` / `avgTicketByMonth`。单位没有丢：在 `:unit` 里。

## 给下一格（board）的话
- 三块板要的指标都在：KPI 卡 = `:revenueTotal` / `:trafficTotal` / `:avgTicket` / `:returnRate`（3 个月合计）；
  矩阵 = `:revenueTotalByStoreMonth`（12 组，键是「月份 / 门店名」）；趋势线 = `:revenueTotalByMonth`（3 点）。
  横向比店还有 `:trafficTotalByStore` / `:avgTicketByStore` / `:returnRateByStore`。
- `:returnAmountTotal` 编译通过但**不是 KPI**（D12 副产品；grill §3 未定），别把它做成第 5 张卡。
- 不要给任何指标加 `:scale`；不要声明 `:supportsSlot :TimeWindow`；不要做红绿灯（D13）。

产物: work/store_monthly_v1/metrics_ext.ttl（S3，14 指标全编译 / 0 按名拒绝）、store_monthly_v1_settings.json（工作区副本：ontology_dir"."、guard.default_window_days=0、big_tables{}、aliases、samples 15 条）、samples.json（S5，15 条 = 12 答 + 3 按名拒绝，含用户点名的「各品类的毛利率是多少？」），并同步镜像到 outputs/users/1/work/store_monthly_v1/（根 + ontology/，cmp 全 same，两份 settings 各自 check_structure 28/28 green、check_samples ALL PASS）
未验证项: ① 看板页面实际渲染没跑（ontology.html / dashboard.json 属 board 格，我被要求不写）：`_fmt` 的代码行为读到了（ratio×100、money→¥、其它走通用数字格式），但客单价 `money_per_visit` 与客流量 `count` 在真实页面上的呈现（无单位后缀）没有渲染证据；② `statement_timeout_ms=8000` / `max_plan_rows=5000000` 没有实测触发（本库查询都是毫秒级、表也没有 ANALYZE 计划），只有 guard.config() 的值被证实；③ 「品类表与月度经营之间不存在可声明的关联」沿用上一格的列清单事实（我自己复核过 14 列与事实表 6 列，但没有、也无法用约束证明「将来不会加品类列」）；④ 注册 profile（features/ontology/profiles/store_monthly_v1/store_monthly_v1_settings.json）仍是 ontology_dir="ontology"、无 aliases/guard/samples，所以**部署后的门面仍会拒绝本文里那几个中文问法** —— 我只能改工作区副本
需要人决定: ① `big_tables` 空导致 `[FAIL] G1a the profile names its big tables — no big_tables`：这是「本库最大表 12 行、无时间戳列」的事实，要人决定是接受这条红，还是改断言（我不编表/列让它变绿）；② 发布/apply 时是否把工作区 settings 副本（ontology_dir"."、aliases、guard、samples）并入注册 profile —— 否则中文问题按名拒绝 + guard 兜 retail DEFAULTS；③ 客单价 `money_per_visit` / 客流量 `count` 在板上没有单位后缀（`_fmt` 没有这两个单位的分支），要不要在 board 声明里补后缀；④ grill §3 的有意未定项仍空着：退货额是否独立成 KPI（指标存在、没做卡）、坪效（口径未定）、按城市分组（D15 排除）；⑤ 品类毛利率的**拒绝文案本身**在管线里是通用菜单句（`I can answer about: …`），事实理由写在 samples.json 的 `_why` 里；若要让用户看到的拒绝句直接说「品类只有目标值、无实际销售额与成本、事实表无品类键」，需要给 :Category 加一个 `:refusalReason`（属结构层，本格不许改 01-structure）

---

# NOTES 追加 —— S6 看板 + S7 教程 + S8 拒绝清单（board 格）

## 这一格读了什么
- `grill.md` 全篇（D1–D17 + 末尾 D18 / D18b 覆盖 D15 的块数；§3 有意未定项一律没补）。
- 本文件上半部分（modeller 的 S1/S2、metrics 的 S3/S4/S5：哪个 IRI 带什么单位、比率为啥不写 `:scale`、`_fmt` 的渲染行为、aliases 是必需的）。
- `metrics_ext.ttl`（14 个指标，唯一可引用的数字来源）、`samples.json`（15 条，含 3 条按名拒绝与它们的 `_why`）。
- `01-structure.ttl` / `02-meaning.ttl`：**只读**，一个字节没动（本节末尾有 `cmp` 记录）。
- 格式参考 `features/ontology/profiles/meeting_v1/dashboard.json`、`tutorial.json`（只抄形状）。
- 读了三个门禁的源码（`gates/check_dashboard.py`、`gates/check_ontology_generic.py` 的 P/T/X 段、`compiler/run_dashboard.py` 的 `_fmt / collect_metrics / resolve_briefing / _execute`）—— 为了知道每条断言到底读哪个字段，而不是猜。

## 产物
1. `work/store_monthly_v1/dashboard.json`（S6）
2. `work/store_monthly_v1/tutorial.json`（S7）
3. `work/store_monthly_v1/ontology.html`（渲染产物，106 KB，由 `graph_view.py` 生成，见下）
4. 本段 NOTES。
5. 镜像：`outputs/users/1/work/store_monthly_v1/` 下同样的三个文件（`cmp` 全 same），并用那份 settings 重跑过 D / T / P / X，结论一致 —— 交付物不是只在某个 agent 目录里才成立。

## 四个面板：是什么、为什么是它、每个数字来自哪条声明

| # | panel id | kind | metric（声明） | 为什么选它 | 页面上的形态（实测） |
|---|---|---|---|---|---|
| ① | `storeMonthRevenue` | `matrix` | `revenueTotalByStoreMonth`（`:groupBy :month, :store_name`） | D15 第②块「门店×月矩阵」，D18 明说不撤 | 12 格（4 店 × 3 月），一格一行事实，无缺月无补零 |
| ② | `monthTrend` | `series` | `revenueTotalByMonth`（`:groupBy :month`） | D15 第③块「月度趋势线」，D18 明说不撤 | 3 个点；**编译器的行序是按值 DESC**，见「排序」一节 |
| ③ | `storeTicket` | `ranked`（`size_by: trafficTotalByStore`） | `avgTicketByStore`（组内 `sum(营业额)/sum(客流量)`）+ 分母 `trafficTotalByStore` | D18 交给 board 判的两块之一：KPI 卡只有合计客单价，按门店的客单价板上此前没有 —— 这正是 D16「掉在客单价」要的那一块 | 4 行；`sort: "asc"` + `client_sort: true`，编译器出厂顺序是 DESC（天河城 27.5602 在最前），要显示「垫底在前」必须前端重排 |
| ④ | `storeReturnRate` | `ranked`（`size_by: revenueTotalByStore`） | `returnRateByStore`（组内 `sum(退货额)/sum(营业额)`）+ 分母 `revenueTotalByStore` | D18 交给 board 判的另一块：D16「掉在退货」；退货率越高越差，所以「最差在前」= 编译器默认的 DESC | 4 行；DESC 正好是想要的方向，不需要 `client_sort` 也说不出反话 |

**没有做营业额排名**（D18 举的例子之一）：营业额已经在 KPI 卡、矩阵、趋势线上各出现一次，再排一次是同一批数换排法（D15 当初正是这个理由）；而客单价、退货率按门店看在这张板上是两块**新**数。这是判断，不是遗漏，理由写进了 `_doc`。

**没有 holes 面板**：`品类毛利率` 不是「已声明、拒绝编译的指标」，而是根本没有指标可声明（编译器按名拒绝 0 个指标）。`:Category` 是**已声明**的类，hole 面板 `requires` 要求指向未声明的类 —— `D1 {pid}: {cls} is still undeclared` 会判它撒谎。所以品类毛利率进 `cannot_see`（S8），不做空洞卡。

## 排序（D2 的陷阱，实测不是转述）
`ontology_inspect(metric=returnRateByStore)` 打印出的 SQL 末尾是 `GROUP BY 门店.门店名 ORDER BY 2 DESC` —— 编译器对分组指标永远 DESC。`run_dashboard` 实测的三组行序：
- `avgTicketByStore` → 27.56 / 24.82 / 21.04 / 20.48（天河城 → 春熙路）：**高在前**。所以「客单价垫底在前」这块声明了 `sort: "asc"` + `client_sort: true` + `sort_note`；不写就会渲染成「最好的门店」。
- `returnRateByStore` → 0.026885 / 0.023212 / 0.018309 / 0.013439：高在前，而退货率高**就是**最差 —— 这块不需要重排，`sort: "desc"` 与出厂顺序一致。
- `revenueTotalByMonth` → `2026-03`(453,800) / `2026-01`(430,400) / `2026-02`(387,100)：**按值排，不是时间序**。趋势线声明了 `client_sort: true`（`sort: "asc"`）要求按月份序展示；月份是定长 YYYY-MM，字典序就是时间序。同一件事也写了 `sort_note`，没有靠「看起来对」蒙过去。
- `revenueTotalByStoreMonth` → 12 格也按值 DESC 出行（天河城先）。矩阵按两个键定位格子，行序不影响落格，但这一点也记下来。

## KPI 卡与那条红（不掩盖）
`kpis` 四张卡：`revenueTotal`（money）/ `trafficTotal`（count）/ `avgTicket`（money_per_visit）/ `returnRate`（ratio），每条 note 写了粒度（一行 = 一个门店的一个月，十二行合计）与口径来源。

`check_dashboard.py` 对 KPI 卡有一条静态断言：**单位不能是裸 `ratio`**。实测结果（两条路径都跑过，agent 副本与共享副本各一次）：

```
  FAIL  D1 kpi returnRate carries a unit a reader can interpret (not a bare ratio) — unit='ratio'; declare :scale "100.0" + :unit "percent", or a unit that names what it is
          got  False
          want True
39 checks, 1 failed
```

这不是我写错了字段，是**两条已定的声明在互相顶**：
- `metrics_ext.ttl` 里 `:returnRate` 的 `:unit` 就是 `"ratio"`，并且**明确不写 `:scale`**（理由：本仓 `_fmt` 对 `ratio` 自己 ×100，再写 `:scale "100.0"` 会乘两次，退货率会变成 221%）；
- `samples.json` 的 `退货率是多少？` 这条 `route` 与 `tolerance 1e-6` 钉的是**未乘 100 的 raw ratio**（0.022142689）；
- 而 D1 要 KPI 卡上的单位「读得懂」，`ratio` 不算。

要让 D1 变绿只有三条路，**三条我都不许走**：改 `metrics_ext.ttl` 的 `:unit`（禁改，而且会连带让 S5 的期望值全部对不上）、改 `samples.json` 的期望（禁改，且那是把门禁哄绿）、或改门禁断言（禁改）。**照实红着**，写进 needs_human。

补充一个实测事实，供决定时参考：**页面上这个数读得对**。`run_dashboard._fmt` 对 `unit == "ratio"` 做 `×100 + '%'`，实测渲染出的 briefing 是「合计退货率 2.2%」；KPI 卡与 briefing 走同一套 `_fmt`（`run_dashboard.py` 的 `_fmt` docstring 原话：「The same presentation rules the page uses」）。所以这条红是**声明卫生**问题（一个裸 `ratio` 声明在别处会被读成 0.02%），不是页面上少了个百分号。

## 单位在页面上的真实呈现（这一格实测的）
`run_dashboard._fmt` 只有两支专门分支：`ratio` → `×100%`、`money` → `¥x,xxx.xx`；其余单位走通用数字格式（整数原样、≥10 一位小数、≥1000 千分位）。实测渲染（原样抄下来）：

```
三个月份平铺看（月度营业额 ¥430,400.00 / ¥387,100.00 / ¥453,800.00）：合计营业额 ¥1,271,300.00、客流量 52,800 人次；合计客单价 24.1 元/人次（先加总再相除），合计退货率 2.2%。
```

- 客单价 `money_per_visit` → 渲染成 `24.1`，**没有单位后缀**；「元/人次」这四个字是我在 briefing 正文里写的展示标签，`metrics_ext.ttl` 的 `:unit` 一个字没改。
- 客流量 `count` → 渲染成 `52,800`，同样没有后缀；「人次」也是正文里的标签。
- 退货率 `ratio` → `2.2%`（`×100` 由 `_fmt` 做，声明里没有 `:scale`）。
- 营业额 `money` → `¥1,271,300.00`。

## briefing：每个数字都是占位符
`briefing.headline` + 8 条 `claims` + `next` 里**没有一个手打数字**：全部是 `{metric}` / `{metric:key}`，由 `run_dashboard.resolve_briefing` 现场填。门禁 D7 的实测：

```
  PASS  D7 no number is typed by hand (every digit came from a placeholder)
  PASS  D7 every claim resolved
  PASS  D7 the headline resolved
       verdict green · breaches [] · assumed []
```

正文里出现的「四家店」「三个月份」「十二行」一律用中文数字——不是为了绕门禁，是因为这些是叙述而不是读数，读数必须走占位符。

`policy`：`[]`（空数组）+ 一句 `_policy_note` 说明「本看板不设任何业务阈值（D13）」。没有 op/value 红线，没有 `assumed: true` 的演示阈值，客单价目标与退货率红线都不存在。D13/D14 也落实到措辞：没有「本月」「近 30 天」，没有同比，只有相邻两个月的比较。

## cannot_see（S8 拒绝清单的落点）：6 条，按名 + 缺哪条声明
1. **品类毛利率** —— 品类表只有 `品类编码 / 品类名 / 目标毛利率`（目标值 0.18 / 0.22 / 0.31，本格自己 `select * from "品类"` 查过），没有实际销售额、没有成本/进价；`月度经营` 六列无品类键，两表 join 不上。缺的不是一行 SQL，是**一列事实数据**：事实表品类键 + 成本/进价列。
2. **坪效** —— 口径未定（`面积平米` 有：新街口 860 / 五道口 640 / 天河城 1020 / 春熙路 720，但周期与「算营业额还是毛利」没定）。
3. **按城市分组** —— D15/D18 排除，不是能力不足（城市列真实存在，四城各一家店）。
4. **同比** —— D9/D14：只有三个月份，没有上年数据，也没有日期列。
5. **退货额独立 KPI 卡** —— `returnAmountTotal` 已编译（合计 28,150 元，见手写 SQL），但 D1 只点名四个数；缺的是用户一句话，不是声明。
6. **任何「本月 / 最近 N 天」时间窗** —— D14 没有当期概念；技术上 `date_trunc` 与 `now() - interval` 在 text 月份上都报类型错误（上一格实测，本格复核过列类型仍是 text）。

**放在哪：** 写在 `dashboard.json` **顶层** `cannot_see`，不写 `briefing.cannot_see`。两个都是渲染器支持的形状（`resolve_briefing` 先看 `briefing.cannot_see`，没有就回退顶层），页面都会显示；实测 `briefing.cannot_see` 渲染出来 6 条、`cannot_see_problems: []`。为什么是顶层：D7 的「不许手打数字」只扫 `briefing` 里的 `cannot_see`，而这六条里必须出现的 0.18/0.22/0.31、860/640/1020/720 是**品类表与门店表的参考值，没有任何指标能产出**（D7/D13 已把它们排除在指标之外），写成占位符只会变成「查不到」。放在顶层是渲染器的既有回退分支（meeting_v1 同形），不是我为变绿新加的开关 —— 但这条边界写在这里，因为它是这一格唯一「靠位置换通过」的地方。

顺带修掉的一个真问题：第一版第 5 条里写了 `{returnAmountTotal}`，而 `collect_metrics → briefing_refs` **只走 `briefing`、不走顶层 `cannot_see`**，于是那个指标没被跑、页面渲染成 `⟪:returnAmountTotal is missing⟫`（实测 `cannot_see_problems: [':returnAmountTotal is missing']`）。改成文字引用指标名后 `cannot_see_problems: []`。这是读源码+跑管线发现的，不是猜的。

## 教程（tutorial.json）：6 步，第 6 步是拒绝
1. `metrics` 先看一个总量：`revenueTotal`、`trafficTotal`（顺带把粒度讲清：一行 = 一个门店的一个月，十二行无重复无缺月）。
2. `metrics` 按月：`revenueTotalByMonth`（月份是 text，实测 `date_trunc` / `now() - interval` 都报类型错误；没有「本期」）。
3. `metrics` 按门店：`revenueTotalByStore`、`trafficTotalByStore`（先看客流）。
4. `metrics` 门店×月矩阵：`revenueTotalByStoreMonth`（十二格还原十二行）。
5. `metrics` 比率口径：`avgTicket`、`returnRate`、`avgTicketByStore`、`returnRateByStore`（先加总再相除；合计客单价 ≠ 十二行比率的算术平均 —— 实测 24.077652 vs 23.480833，两个数不是一个）。
6. `refusals` 「各品类的毛利率是多少？」：`items = ["Category", "AllStoreMonths"]`，正文写事实理由（只有目标毛利率、无实际销售额与成本、事实表无品类键、join 不上）并点明「要能答，得给事实表补品类键 + 成本/进价列」。
   选这两个 item 不是凑数：实测 `tutorial_api.py --mode definition --class Category` 返回 `{"ok": false, "error": "Refusal: :Category has no owl:equivalentClass axiom — nothing to compile"}`（品类这个类连 predicate 都编译不出来＝没有到事实表的路），而 `--class AllStoreMonths` 返回 `{"ok": true, "predicate": "1=1", "table": "月度经营", "rows": 12}`（我们真正拥有的是十二个门店月）。两者并排，就是「缺一列事实数据」的图解。
   教程正文一律不写阿拉伯数字读数（也没有占位符机制可依赖 —— `tutorial_api` 不做占位符替换，写了 `{avgTicket}` 会原样显示），读数让每一步的面板现跑：T4 实测打印 `revenueTotal=1271300 · trafficTotal=52800 · revenueTotalByMonth=2026-03`。

## ontology.html 怎么来的（任务里那条命令对不上，照实记）
任务给的命令是 `run_dashboard.py --profile <settings>`，但**本仓的 `run_dashboard.py` 只打印 JSON payload，不写 HTML**（源码 `main()` 最后是 `print(json.dumps(payload…))`；实测跑出来 200 多 KB 的 JSON、目录里没有新 html）。真正的生成器是 `compiler/graph_view.py`，`workbench/serve_ui.py::regenerate()` 用的就是它。我用的命令（与 `regenerate()` 同形）：

```
$PY features/ontology/compiler/graph_view.py \
  --ns "https://cube.local/ontology/store_monthly_v1#" \
  --ontology-dir <profile>/ --overlay <profile>/metrics_ext.ttl \
  --dsn "host=127.0.0.1 port=5433 dbname=store_monthly_xlsx user=langconfig password=$ONTOLOGY_DB_PASSWORD" \
  --title "门店月度经营" --out <profile>/ontology.html
```

输出：`== wrote ontology.html — 106 KB, self-contained`；`structure 3 · meaning 1 · metrics 14 compiled + 0 refused`；`gate: 18/18 positioned, 18/18 documented, 3/3 classes list their properties, 4/4 classes have individuals — PASS`。
自检：html 里 `/Users/` 出现 **0** 次、密码字面量 **0** 次（`grep -c` 两条都是 0），`<title>门店月度经营 —— 图谱与文档（由 TTL 生成）</title>`。

## 门禁最后一行（原样；`PY=../.venv/bin/python`，cwd=`backend/`）
agent 副本与共享副本各跑一遍，结论相同：

- `check_dashboard.py --profile <settings>` → **`39 checks, 1 failed`**，唯一 FAIL 是上面那条 `D1 kpi returnRate …unit='ratio'`。其余：D0 10/10 PASS、D1 面板形状全 PASS、D2 两块 ranked 全 PASS、D7 全 PASS、verdict green。
- `check_ontology_generic.py --family T` → **ALL GATES PASS**（T1–T5；T4 打印 `revenueTotal=1271300 · trafficTotal=52800 · revenueTotalByMonth=2026-03`）。
- `check_ontology_generic.py --family X` → **ALL GATES PASS**（X1 / X1b / X2 / X2b）。
- `check_ontology_generic.py --family P` → **ALL GATES PASS**（P1 / P2 / P3；`4/4 declared classes on the page: AllStoreMonths, Category, Store, StoreMonth`）。
- `check_samples.py --profile <settings>` → **ALL SAMPLES PASS**（15 条；含三条按名拒绝）。
- `check_structure.py --profile <settings>` → **`28 checks · 0 failed · green`**（S1 仍绿，01/02 未动）。
- 全量 `check_ontology_generic.py`（不带 `--family`）→ **SOME GATES FAILED**，唯一红行仍是那条已知红：`[FAIL] G1a the profile names its big tables — no big_tables`（本库最大表 12 行 / 16 kB、全库无 timestamp 列 —— 事实，不编表不编列）。NOT RUN 两条：`R2 definition == hand SQL`（本 profile 无 `truth.json` 的 `_definitions`）、`window gate`（无指标声明 `:supportsSlot :TimeWindow`）。P2 这次**不再红**（`ontology.html` 已生成）。

## 每个数字的手写 SQL 佐证（不经过管线，本格自己跑的）
```
-- 合计层
select sum("营业额"), sum("客流量"),
       round(sum("营业额")::numeric/nullif(sum("客流量"),0),6),      -- 24.077652
       round(sum("退货额")::numeric/nullif(sum("营业额"),0),9),      -- 0.022142689
       round(avg("客单价"),6), count(*)                              -- 23.480833 / 12
from "月度经营";
→ 1271300 | 52800 | 24.077652 | 0.022142689 | 23.480833 | 12

-- 按门店（JOIN 门店）
天河城店 457500 16600 27.5602 0.026885 / 新街口店 374800 15100 24.8212 0.023212
五道口店 256700 12200 21.0410 0.018309 / 春熙路店 182300  8900 20.4831 0.013439

-- 按月份
2026-01 430400 17900 24.0447 0.022537 / 2026-02 387100 16000 24.1938 0.023250
2026-03 453800 18900 24.0106 0.020824

-- 矩阵与加总恒等式（D3 在我这一层手工复核）
cells=12  matrix_sum=1271300  total=1271300
weighted_ticket=24.077652  ticket_weighted_back=24.077652          -- 组值按客流加权回到合计
rate_weighted_back=0.022142689  rate_total=0.022142689             -- 组值按营业额加权回到合计

-- 参考数据（坪效/品类两节用到的）
门店: S01 新街口店 南京 860 / S02 五道口店 北京 640 / S03 天河城店 广州 1020 / S04 春熙路店 成都 720
品类: C1 生鲜 0.18 / C2 日配 0.22 / C3 百货 0.31
月度经营 六列: 月份 text, 门店编码 text, 营业额 bigint, 客流量 bigint, 客单价 numeric, 退货额 bigint  ← 无品类键
```
在册的 14 个指标与 `:returnAmountTotal` 的合计 28,150 元、矩阵 12 格逐格值，管线（`run_dashboard.py`）与上面的手写 SQL 逐值相同。

## 没改的东西
`01-structure.ttl` / `02-meaning.ttl` / `metrics_ext.ttl` / `samples.json` / `store_monthly_v1_settings.json` —— 一个字节没动（需要核对时：`cmp` 与上一格产物相同；本格只新增 `dashboard.json`、`tutorial.json`、`ontology.html` 并追加本段）。

产物: work/store_monthly_v1/dashboard.json（S6：4 面板 = 门店×月矩阵/月度趋势/门店客单价排名(asc+client_sort)/门店退货率排名(desc)，KPI 4 卡走 kpis 不占位，policy 空数组）、tutorial.json（S7：6 步，第 6 步按名拒绝品类毛利率）、ontology.html（graph_view.py 生成，106 KB，P1/P2/P3 全绿）；镜像到 outputs/users/1/work/store_monthly_v1/（cmp same，那边的 settings 重跑 D/T/P/X 结论相同）
未验证项: ① `client_sort` / `sort: "asc"` 是否真被页面渲染器执行：本仓没有看板前端代码（`serve_ui` 只渲染图谱页，不渲染 panels），实测到的只有「编译器出厂顺序确实是 DESC」（avgTicketByStore 27.56 在前、revenueTotalByMonth 2026-03 在前）与「D2 只检查声明里有没有 client_sort」——若前端不重排，客单价那块会渲染成「最好的门店」、趋势线的 x 轴会乱序；② KPI 卡本身的格式化没有渲染证据：卡与 briefing 共用 `_fmt`（docstring 这么说），但卡片的前端代码不在本仓，只实测了 briefing 的渲染文本（24.1 / 52,800 / 2.2% / ¥1,271,300.00）；③ `cannot_see` 写在顶层而不是 `briefing.cannot_see`，D7 的「不许手打数字」因此不扫这六条——这是渲染器的既有回退分支，但「顶层不扫」这条边界本身没有被任何门禁断言守过，属我读源码得到的行为；④ G1a 红与 P2 不再红都只在本工作区副本上验证，注册 profile（features/ontology/profiles/store_monthly_v1/）仍没有这三个文件
需要人决定: ① `D1 kpi returnRate … unit='ratio'` 这条红要不要修、怎么修：修法只有改 `metrics_ext.ttl`（`:unit "percent" + :scale "100.0"`，会连带改 `samples.json` 里退货率/客单价的期望值）或接受这条红；两边都是已定的决定（`:scale` 双乘、S5 钉 raw ratio），不是我能单方面动的；② 「退货额」要不要做成第五张 KPI 卡（指标已编译，D1 只点名四个数，grill §3 列为有意未定）；③ 坪效的口径（按月还是整期、营业额还是毛利）—— 定了才能声明；④ 要不要按城市看（D15/D18 目前排除）；⑤ `:Category` 是否加 `:refusalReason`，让「品类毛利率」的拒绝句在页面上直接说出事实理由（现在是 NL 通用菜单句，事实理由只在 `samples.json` 的 `_why` 与本看板 cannot_see 里）；⑥ 注册 profile 是否并入工作区这份 settings（`ontology_dir="."`、aliases、guard、samples）与这三个新文件

### metrics 格（补丁格：修掉 D1 唯一那条红 —— 退货率单位）2026-11-25

**只改了 `metrics_ext.ttl` + `samples.json`**；`01-structure.ttl` / `02-meaning.ttl` / `dashboard.json` /
`tutorial.json` / `store_monthly_v1_settings.json` 一字未动（cmp 与上一格产物相同，mtime 仍 13:55/13:56/14:11）。

改了什么：
- `:returnRate` / `:returnRateByStore` / `:returnRateByMonth`：`:unit "ratio"` → `:unit "percent" ; :scale "100.0"`。
  `:businessDescription` 重写，把三段理由写进文件：① `:scale` 由**编译器乘进 SQL**（不是显示层）；
  ② `unit=percent` 在 `run_dashboard._fmt` 里走通用分支、**不再乘第二次**；③ 旧写法（只写 ratio、不写 scale）
  在 briefing 读 2.2%、在 KPI 卡按裸比率读 0.02，差 100 倍。
  以及**为什么三个一起改**：同屏三处退货率换尺子，等于让读者拿两把尺子比；D1 只检查 KPI 卡，
  `returnRateByStore` / `returnRateByMonth` 跟着改是口径一致性，不是过门禁。
- `avgTicket` / `avgTicketByStore` / `avgTicketByMonth` 的 `:unit "money_per_visit"` **没动**（门禁已绿且自解释）。
- 文件头第 22–23 行「没有 :scale：渲染器对 ratio 自己 ×100，再声明 :scale 会乘两次」是**过时且对旧写法成立、
  对新写法不成立**的注释，整段改写；第 42–44 行「比率单位写 ratio」的取舍说明同步改。
- `samples.json`：三条退货率样例的 `route` 改成 `sum("退货额")::numeric * 100 / nullif(sum("营业额"),0)`，
  `_why` 里的数字全部换成**实测百分比**。route 故意写 `*100`：若还写裸 ratio，`check_samples` 会用
  `_declared_scale()` 把编译值除回 100 再比、照样绿 —— 那就钉不住单位了（这一点写进了样例的 `_why`）。
  其余 12 条样例一字节未动。

**实测（都能重放；库 store_monthly_xlsx @127.0.0.1:5433 user langconfig）**

| 事实 | 怎么测的 | 值 |
|---|---|---|
| `:scale` 编译进 SQL，乘的是**整个比值** | `sqlgen.py:1127` `body = f"({m.scale}) * ({body})"`；`ontology_inspect(metric=returnRate, source_dir=work/store_monthly_v1)` | `SELECT (100.0) * (((SELECT sum(退货额) …)::numeric) / NULLIF((SELECT sum(营业额) …),0))`，notes 含 `scaled by 100.0 (declared :scale)`，**value = 2.214268858648627389000**（旧：0.02214268858648627389） |
| 合计 | 手写 SQL `sum(退货额)*100/nullif(sum(营业额),0)`（`db_query`） | `2.2142688586486274` —— 与编译值逐位相同 |
| 按门店（编译值） | `nl.ask("按门店看退货率")` → `returnRateByStore` | 天河城 2.6885245901639343 / 新街口 2.321237993596585 / 五道口 1.8309310479158551 / 春熙路 1.3439385628085574 |
| 按门店（第二路线） | 手写 `sum*100/sum … GROUP BY 门店名` | 2.6885245901639344 / 2.3212379935965848 / 1.8309310479158551 / 1.3439385628085573（差 ≤1e-15，容差 1e-6） |
| 按月份（编译值） | `nl.ask("按月份看退货率")` | 2026-01 2.253717472118959 / 2026-02 2.324980625161457 / 2026-03 2.0824151608638166 |
| 按月份（第二路线） | 手写 SQL | 2.2537174721189591 / 2.3249806251614570 / 2.0824151608638167 |
| 单行区间 | `min/max(退货额*100/营业额)` 逐行 | 1.2773722627737226 … 2.7310924369747899（= 旧 0.0128…0.0273 的同一批数） |
| **没有双乘** | `run_dashboard.py --profile …` 的渲染文本 | headline：`合计退货率 2.21`；claim rate：`2.69、2.32、1.83、1.34`（不是 221.43 / 268.85）；`kpis[returnRate].result` = `unit:"percent", scale:"100.0", rows:[[2.2142688586486274]]` |

**门禁（profile venv = `backend/.venv/bin/python`，`--profile …/work/store_monthly_v1/store_monthly_v1_settings.json`；
`check_dashboard.py` 的相对 `--profile` 是相对 `compiler/` 解析的，必须给绝对路径）**

| 门 | 结果 | 与上一格比 |
|---|---|---|
| `check_samples.py` | `ALL SAMPLES PASS`（15 条 gated / 15 offered，退货率 3 条走 `*100` route 逐值 match） | 绿 → 绿（值从 0.x 变 2.x，闸门仍靠两条独立路线对） |
| `check_dashboard.py` | **39 checks, 0 failed**（`PASS D1 kpi returnRate … unit='percent'`） | 39/1 failed → **0 failed**：唯一那条红消失 |
| `check_ontology_generic.py --family C` | `ALL GATES PASS`（compiled 14 · refused by name 0） | 绿 → 绿 |
| `check_ontology_generic.py --family T` | `ALL GATES PASS` | 绿 → 绿 |
| `check_ontology_generic.py --family M` | **`unknown gate family/families: ['M']`（exit 2）** | 这个门不存在：`check_ontology_generic.py:855` 的合法家族只有 C/R/G/P/T/N/S/W/X |
| `check_ontology_generic.py`（全部家族） | `SOME GATES FAILED`，唯一 `[FAIL] G1a the profile names its big tables — no big_tables` | 与上一格同一条红（本库最大表 12 行、无 timestamp 列），**不是本格修的** |

两份工作区副本已同步：`work/store_monthly_v1/{metrics_ext.ttl,samples.json}`（本 agent 目录）与
`outputs/users/1/work/store_monthly_v1/{…}`（`ontology_inspect`/`edit_file` 认的那一份）`cmp` 相同，两边的门禁重跑结论一致。

产物: work/store_monthly_v1/metrics_ext.ttl（三个退货率指标 `:unit "percent" + :scale "100.0"`、文件头与单位说明改写、167 三元组不变）、work/store_monthly_v1/samples.json（3 条退货率样例 route `*100` + `_why` 用实测百分比；15 条总数不变）、本 NOTES 段；两份副本已 `cmp` 同步
未验证项: ① KPI 卡前端拿到 `unit="percent"` 后到底把单位标签渲染成什么字符串：本仓没有卡片前端代码，实测到的只有 `run_dashboard` 的 payload（`unit:"percent", scale:"100.0"`）与 briefing 文本（`2.21`），卡上的「%」标签未亲眼见；② **briefing 正文丢了「%」号**：`dashboard.json` 的 headline 写 `合计退货率 {returnRate}`、claim 写「从高到低：{returnRateByStore:…}、…」，改单位前 `_fmt` 对 ratio 会自己补 `%`，现在走 percent 通用分支只出裸数字（实测 `合计退货率 2.21`、`2.69、2.32、1.83、1.34`）——数字对、读法靠单位标签，文案是否要补「%」属 board 的文件，我没改；③ `:scale` 在其它渲染路径（如果本仓还有第二个前端）会不会再乘一次：只测到 `run_dashboard._fmt` 这一处；④ `02-meaning.ttl` 里 `:return_rate :unit "ratio"` 与其 businessDescription「单位按 ratio 记（看板按 ×100 显示成百分比）」现在与 overlay 矛盾，我没权限改
需要人决定: ① `02-meaning.ttl` 的 `:return_rate` 单位句要不要重写成 percent + scale（S2 是 modeller 的文件，本格只追加不改）；② `dashboard.json` 的 briefing 文案要不要在 `{returnRate}` / `{returnRateByStore:…}` 后面补「%」（否则页面正文读作裸数字 2.21，靠卡片单位标签解释）；③ 上一格挂着的两条红线仍未拍：G1a `no big_tables`（本库事实如此）、`:Category` 要不要加 `:refusalReason`

### modeller 格（补丁格：把 S2 的退货率单位对齐到 S3）2026-11-25

**只改了 `02-meaning.ttl`**（33 → 34 三元组，+1 是新增的 `:scale`）。`01-structure.ttl` /
`metrics_ext.ttl` / `samples.json` / `dashboard.json` / `tutorial.json` / `store_monthly_v1_settings.json`
一字未动（`cmp` 与上一格产物相同：01 SAME / metrics SAME / samples SAME / dashboard SAME / tutorial SAME）。

改了三处（`diff -u` 只有这三个 hunk）：
1. `:return_rate`：`:unit "ratio"` → `:unit "percent" ; :scale "100.0"`，`businessDescription` 整段重写：
   值是**已乘过 100 的百分点数**（合计 2.2142688586486274 = 2.21%，单店 1.3439…2.6885，单月 2.0824…2.3250，
   单行 1.2774…2.7311，全部带实测）；为什么 percent+scale 而不是 ratio（`:scale` 被编译器乘进 SQL、
   `_fmt` 只对 `ratio` 再 ×100 → percent 是唯一「乘一次、不会双乘」的路；裸 ratio 又被 D1 判成读不懂的单位）；
   为什么三个退货率指标必须同一把尺子（只改合计不改分组，板上 2.21 与 0.027 会被读成百分之一/100 倍差）；
   D13 无红线无「多少算超标」，判定权仍在业务手里；D5/D10/D12 口径一字未改（含「不随退货金额摆动」来自 D10 分母选择）。
   旧的「单位按 ratio 记（看板按 ×100 显示成百分比）」与「无量纲（0…1）」两句已删除，全文不再把退货率写成 ratio。
2. 第 64–69 行「两个比率」节头注释：补三行单位说明（客单价 `money`；退货率 `percent` + `:scale "100.0"`，
   乘 100 在编译进 SQL 的那一侧，渲染器对 percent 不再乘）。
3. `:AllStoreMonths` 里唯一一处单位相关表述：`退货率处处落在 0…1 之内` → `0…100 之内（percent 口径，见 :return_rate）`。
   （`:revenue` / `:traffic` / `:return_amount` / `:month` / `:avg_ticket` / `:avg_ticket_stored` 的字节未动。）

**实测（都能重放）**

| 事实 | 怎么测的 | 值 |
|---|---|---|
| 编译值未被 S2 影响、`:scale` 仍在 SQL 里 | `ontology_inspect(metric=returnRate, source_dir=work/store_monthly_v1)`（改后重跑） | `SELECT (100.0) * (((SELECT sum(退货额) …)::numeric) / NULLIF((SELECT sum(营业额) …),0))`，`value = 2.214268858648627389000`，notes `scaled by 100.0 (declared :scale)` |
| 合计（第二路线，手写 SQL） | `db_query` `select sum("退货额")::numeric*100/nullif(sum("营业额"),0) from "月度经营"` | `2.2142688586486274` |
| 按门店（第二路线） | `db_query` JOIN 门店 `GROUP BY 门店名` | 天河城 2.6885245901639344 / 新街口 2.3212379935965848 / 五道口 1.8309310479158551 / 春熙路 1.3439385628085573 |
| 按月份（第二路线） | `db_query` `GROUP BY 月份` | 2026-01 2.2537174721189591 / 2026-02 2.3249806251614570 / 2026-03 2.0824151608638167 |
| 单行区间（第二路线） | `db_query` `min/max(退货额*100/营业额)` | 1.2773722627737226 … 2.7310924369747899（12 行） |
| `:scale` 是编译期乘法 | `compiler/sqlgen.py:1127-1128` `body = f"({m.scale}) * ({body})"`、`:1133-1134` notes | 读到源码行 |
| `_fmt` 只对 ratio ×100 | `compiler/run_dashboard.py:371-374`：`if unit == "ratio": return f"{v*100:.1f}%"`；percent 落到通用分支（2.2142688 → `"2.21"`，`:>10` 分支不命中） | 读到源码行；所以 percent+scale 不会双乘 |

**门禁（原样）**

| 门 | 命令 | 结果 |
|---|---|---|
| S3/C | `check_ontology_generic.py --family C --profile …/work/store_monthly_v1/store_monthly_v1_settings.json` | `ALL GATES PASS`（compiled 14 · refused by name 0） |
| S1/S2 结构 | `check_structure.py --profile …` | `28 checks · 0 failed · green` |
| S5 | `check_samples.py --profile …` | `ALL SAMPLES PASS`（退货率 3 条 route 仍逐值 match：`2.2142688586486274`） |
| 全家族 | `check_ontology_generic.py --profile …`（无 `--family`） | `SOME GATES FAILED`，唯一 `[FAIL] G1a the profile names its big tables — no big_tables` + `R2 … NOT RUN`（**与改前同一条已知红，不是我引入的**） |
| 回归 | `check_dashboard.py --profile …`（文件未动，只验 S2 没漏进渲染） | `39 checks, 0 failed` |

两份副本已同步：`work/store_monthly_v1/02-meaning.ttl` ↔ `agents/agent_393/work/store_monthly_v1/02-meaning.ttl`
（`cmp` 两次 SAME，md5 均 `a26f67277999a65dbdd11b4d9cefcb13`）。

产物: work/store_monthly_v1/02-meaning.ttl（`:return_rate :unit "percent" ; :scale "100.0"` + businessDescription 按新口径重写、节头单位说明、`:AllStoreMonths` 的 0…1→0…100；33→34 三元组）、镜像 agents/agent_393/work/store_monthly_v1/02-meaning.ttl（cmp 两次 SAME）、本 NOTES 段；01/metrics_ext/samples/dashboard/tutorial/settings 全部 cmp SAME 未动
未验证项: ① 「继续写 ratio 再声明 :scale 就会乘两次 → 221.43%」是读 `run_dashboard.py:371-374` 源码推的，没有跑过第二份声明去实测那个数字（本格不能改 metrics_ext）；② `:scale` 是否还有别的渲染/消费路径（如第二个前端）会再乘一次：只测到 `_fmt` 这一处；③ S2 的 `:avg_ticket :unit "money"` 与 S3 的 `avgTicket :unit "money_per_visit"` 标签不一致（前者会被任何按 `ratio` 分支格式化的消费者当普通金额）—— 本格的指令是 avg_ticket 一个字节不许动，所以只记录、没改，也没有门禁断言 S2/S3 的单位字符串必须相等；④ `ontology.html` 是上一格用旧 `02-meaning.ttl` 生成的（含 `ratio` 字样），本格按「只改 02-meaning.ttl」没重渲染
需要人决定: ① 无（本格是把 metrics 上一格挂着的第①条做成已定决定；`avg_ticket` 单位标签是否与 S3 对齐属我下一格的活，不需要用户拍板）


## CLI 补齐（2026-11-25，实测，非模型写入）
- `guard.big_tables = {"月度经营": "月份"}`：check_ontology_generic G1a 要求非空；实测三表行数 12 / 4 / 3，只有 `月度经营` 是事实表，时间列 `月份`（TEXT，YYYY-MM）。
- `default_window_days = 0`：只有 3 个月，不做窗口裁剪。
