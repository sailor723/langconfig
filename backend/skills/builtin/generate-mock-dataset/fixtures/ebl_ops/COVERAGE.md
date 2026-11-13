# team-2（EBL OS）指标 × 表结构 对照表 —— 先证明"能算"，再建库

**用途**：构建本体之前，把方案里**每一个**可被问、可被考核、可被止损触发的量，逐条对到一张表的某一列上。
对不上的，要么补列（合法），要么进拒绝清单（诚实）。这张表就是数据集的验收标准：
**表建完之后，本体要声明的指标必须全部落在"可算"列里**，否则先改表、别改本体。

来源：`client/team-2/11 亿营收目标与防御性毛利守护方案.MD`（下称"方案"，§=章节号）

---

## 一、总览：方案里到底有多少个"量"

| 类别 | 条数 | 说明 |
|---|---|---|
| 营收/规模 | 6 | 11 亿、9 亿、+22%、季度 2.5/2.7/2.9/2.9、增长三桶 1.1–1.5 亿、缺口 2 亿 |
| 毛利 | 7 | 加权 18–19%、硬地板 17.5%、季度预警 17%、三档区间（差异化25–28/标准15–18/低毛利13–16）、微改良 25–28%、认证溢价 2–3% |
| 低毛利订单治理 | 5 | ≤25%（≈2.75 亿）、仅限利用率<70% 产线、双签、提成减半、6 个月复审 |
| 客户 | 6 | 客户分级四维、A/B/C 名单、核心客户 12 家、流失 ≤2 家、边界争议 ≤5%、新客只走转介绍/展会 |
| 交付 | 2 | 核心客户订单准时交付率、产能利用率（整体交付率属范围外） |
| 降本 | 4 | 前 10 大供应商采购成本降 3–5%、账期重谈、低效产线关停/合并、非生产性支出冻结 |
| 人员 | 2 | 2 800 人、6 个部门、不裁员降本 |
| 改进/认证 | 3 | 微改良 3–5 个、认证 1–2 项、客户验证通过与否 |
| 止损触发 | 3 | Q2 末（流失>2 或季度毛利<17%）、Q3 中（微改良验证不通过）、全年（低毛利>25% 或毛利<17.5%） |
| 考核 | 3 | 销售（营收×毛利×回款）、研发（微改良数+认证）、生产（核心客户准时率+利用率） |

---

## 二、逐条对照（方案原句 → 表/列 → 本体可声明的指标）

### A. 营收与规模

| 方案原句（§） | 落在哪 | 本体可声明的指标 | 状态 |
|---|---|---|---|
| 「去年营收 9 亿」（§一） | `order_lines.revenue` where `orders.fiscal_year=2025` | `revenueFY2025` | ✅ |
| 「年度营收目标 11 亿」（§一） | 同上 FY2026 | `revenueFY2026`、`revenuePlan`（策略参数） | ✅ |
| 「+22%」 | 两者之比 | `revenueYoY` | ✅ |
| 「Q1 2.5 / Q2 2.7 / Q3 2.9 / Q4 2.9 亿」（§四） | `orders.quarter` | `revenueByQuarter`、`revenueVsPlanByQuarter` | ✅ |
| 「B 0.6–0.8 亿 / C 0.3–0.4 亿 / A 0.2–0.3 亿」（§四） | `order_lines.growth_bucket` | `incrementalByBucket`（A/B/C 三档增量） | ✅ |
| 「覆盖 2 亿缺口依赖低毛利填产能订单」（§十三） | `tier='低毛利走量'` 的 increment | `gapFilledByLowMargin`、`gapRemaining` | ✅ |

### B. 毛利（红线）

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「加权毛利目标 18–19%」（§一/§四） | `Σ(revenue×gross_margin)/Σrevenue` | `weightedGrossMarginFY` | ✅ 需按**营收加权**（不是行平均，两种口径差 0.4 个点以上） |
| 「全年硬地板 17.5%」（§一） | 同上 + `policies` | `marginFloorBreached`（布尔） | ✅ |
| 「季度预警 17%」（§四） | 按季度加权 | `weightedGrossMarginByQuarter`、`quarterWarningBreached` | ✅ |
| 「差异化 25–28%（§四）」 | `order_lines.tier='差异化'` | `grossMarginByTier` | ✅ |
| 「标准品 15–18%」（§四） | 同 | 同 | ✅ |
| 「低毛利走量 13–16%」（§四） | 同 | 同 | ✅ |
| 「微改良 25–28% + 认证溢价 2–3%」（§三/§四） | `products.tier='微改良'`、`certification_premium` | `grossMarginMicroImproved`、`certificationPremiumLift` | ✅ |
| 「B 类 17–19% / C 类 13–16% / A 类 22%+」（§三，按**客户分级**给的毛利） | `customers.segment` × 毛利率 | `grossMarginBySegment` | ✅ **与"按产品档位"是两个不同切分**，两个都要能算 |

### C. 低毛利订单治理（最容易只有结论、没有数据的部分）

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「低毛利订单占比 ≤25%，约 2.75 亿」（§四） | `tier='低毛利走量'` 营收 / 全部营收 | `lowMarginRevenueShare` | ✅ |
| 「仅限产能利用率 <70% 产线」（§四） | `order_lines.production_line_id → production_lines.utilization` | `lowMarginOnIdleLinesShare`、`lowMarginViolations`（必须 0） | ✅ **约束性**：生成器只允许从 <70% 的产线抽 |
| 「销售总监 + 财务总监双签」（§四） | `low_margin_approvals(signed_by_sales, signed_by_finance, signed_at, review_due_at)` | `lowMarginApprovalCoverage`、`approvalMissing` | ✅ 需要一张审批表，否则"双签"只是一句话 |
| 「提成减半」（§四） | `order_lines.commission_factor`(1.0/0.5) | `commissionHalvedCoverage` | ✅ 只记"按规则打了折"，不记工资金额（薪酬不进库） |
| 「6 个月复审」（§四） | `low_margin_approvals.review_due_at` | `lowMarginReviewOverdue` | ✅ |

### D. 客户与分级

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「四维分级：毛利率、年采购额、回款准时率、比价拖账行为」（§六） | `customers.gross_margin_2025 / purchase_amount_2025 / on_time_payment_rate / price_compare_behavior` | `customerScorecard`（四维原值） | ✅ 四维都在列上 |
| 「3 项以上落 A 档 → A 类」 | 每维的**档位**列：`dim_margin_band / dim_purchase_band / dim_payment_band / dim_behavior_band` | `segmentComputed`（可由四档复算，与 `segment` 比对） | ✅ **必须存档位**，只存原值无法复算判档 |
| 「边界客户由销售副总+财务总监联合裁定」（§六） | `customers.is_boundary`、`customers.arbitrated_by` | `boundaryCustomerShare`（须 ≤5%） | ✅ |
| 「核心客户清单 12 家、Q1 锁定、全年不轻易调整」（§七） | `core_customers(customer_id, locked_at, approved_by)` | `coreCustomerCount`、`coreRevenueShare` | ✅ |
| 「核心客户流失 ≤2 家」（§一） | 核心清单 ∩ FY2025 有单 ∖ FY2026 有单 | `coreCustomerChurn` | ✅ 且要声明"FY2025 的核心清单不可知"这一限制 |
| 「新客只走转介绍和展会存量转化，不做陌拜」（§三） | `customers.source_channel`（值域：转介绍/展会存量转化/存量老客户） | `newCustomerByChannel`、`coldCallShare`（必须 0） | ✅ |
| 「新客只考核有效询盘数」（§七） | `leads(source_channel, is_qualified, converted_customer_id)` | `qualifiedLeads`、`leadConversion` | ✅ 需要 leads 表 |

### E. 交付与产能

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「生产只考核核心客户订单准时交付率」（§七） | `orders.promised_date/actual_date` + `core_customers` | `onTimeDeliveryRateCoreCustomers` | ✅ |
| 「不追求整体交付率大幅提升」（§十，范围外） | 同上（全体客户） | `onTimeDeliveryRateAll` **可算但属范围外** | ⚠️ 能算 ≠ 该考核：本体要把它标成"范围外"，不是拒绝 |
| 「产能利用率」（§七/§八） | `production_lines.utilization` | `lineUtilization`、`idleLineCount` | ⚠️ **输入而非事实**：库里没有班次工时，利用率是方案给的口径值，本体须注明"不可复算" |
| 「关停/合并利用率最低产线」（§八） | `production_lines.status`、`closed_at` | `linesClosed`、`capacityRemoved` | ✅ |

### F. 降本

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「前 10 大供应商采购成本降 3–5%」（§八） | `suppliers(is_top10, spend_2025, spend_2026, unit_price_index_2025/2026)` | `purchaseCostReductionTop10` | ✅ 需要价格指数列，否则"降 3–5%"只能拿总额差凑（会被人均产量/结构变化污染） |
| 「账期重谈」（§八） | `suppliers.payment_days`（2025 vs 2026） | `paymentTermsExtension` | ✅ 1 家 NULL（病理） |
| 「行政部冻结非生产性支出，出清单与审批规则」（§八） | `opex_items(category, amount_2025, amount_2026, freezable, frozen_at, approved_by)` | `opexFrozenAmount`、`opexReduction` | ✅ |

### G. 人员

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「约 2 800 人，6 个部门」（§二） | `employees(department, hired_at, left_at)` | `headcount`、`headcountByDept` | ✅ |
| 「不裁员降本 / 人员不能快速缩减」（§十/§二） | `left_at` 的离职量 | `attrition`、`noLayoffCompliance`（离职原因需列） | ✅ 加 `leave_reason`（主动离职/退休/合同到期/裁员）→ 才能证明"没裁员" |

### H. 微改良与认证

| 方案原句（§） | 落在哪 | 指标 | 状态 |
|---|---|---|---|
| 「微改良 3–5 个改进点」（§三） | `micro_improvements(kind='微改良')` | `microImprovementCount` | ✅ |
| 「出口检测认证 1–2 项」（§三） | 同表 `kind='认证'` | `certificationCount`、`certifiedRevenueShare` | ✅ |
| 「客户验证通过/不通过 → 资源回撤」（§九） | `status`、`verified_at`、`retreated_at` | `microImprovementVerifiedRate` | ✅ |

### I. 止损触发（规则可执行才行）

| 触发（§九） | 需要的数据 | 状态 |
|---|---|---|
| Q2 末：核心客户流失>2 家 **或** 季度加权毛利<17% | `coreCustomerChurn` + `weightedGrossMarginByQuarter` | ✅ 两条都能算，触发器就是一个布尔 |
| Q3 中：微改良客户验证不通过 | `micro_improvements.status/verified_at` | ✅ |
| 全年：低毛利占比>25% **或** 加权毛利<17.5% | 两个比率 | ✅ |
| 「阈值本身（17.5/17/25%/<70%/3–5%/2 家）」 | **不进表** → 进本体 `policies` | ✅ 阈值是策略，不是数据；库里只存事实 |

### J. 制度切换（影响一切时间窗口）

| 方案（§六） | 实现 | 状态 |
|---|---|---|
| 第 1 周口径统一 / 第 2 周华南试点 / 第 3 周定义双签 / 第 4 周全公司推开 | `rule_regimes(at, change)` 四行 + `customers.segment` 在 2026-03-20 前为 NULL、`segment_scored_at` 分区 | ✅ 于是"分级前的营收按 A/B/C 拆"会被明确拒绝 |

---

## 三、表结构（9 维度表 + 1 事实层 + 2 治理表 = 12 张）

```
维度        customers(180)  products(420)  production_lines(32)  suppliers(40)  employees(2800)
           core_customers(12)  micro_improvements(7)  opex_items(28)  leads(≈900)
事实        orders(≈2400) ── order_lines(≈9600) ── order_adjustments(≈1200)
治理        low_margin_approvals(≈600)  rule_regimes(4)
```

**关键列（相对初稿新增，全部是为了"能算"而不是"好看"）**

- `customers`：`dim_*_band` 四个档位列（判档可复算）、`is_boundary`、`arbitrated_by`、`source_channel`、`segment`+`segment_scored_at`、`entered_at`、`on_time_payment_rate`（可 NULL）
- `order_lines`：`tier`、`growth_bucket`、`gross_margin`、`revenue`、`cost`、`production_line_id`、`certification_premium`、`approval_id`、`commission_factor`
- `orders`：`fiscal_year`、`quarter`、`promised_date`、`actual_date`、`revenue_header`
- `suppliers`：`is_top10`、`payment_days`(2025) / `payment_days_2026`、`unit_price_index_2025/2026`
- `employees`：`leave_reason`（证明"没裁员"）
- `leads`：`source_channel`、`is_qualified`、`converted_customer_id`

---

## 四、算不出来 / 不该算的（拒绝清单，写进 manifest 的 `refused`）

| 业务会问 | 为什么答不了 | 处置 |
|---|---|---|
| **引领性产品占比** | §三/§十明确放弃；库里也没有"引领/跟随"标签 | **拒绝**（范围外决策，不是数据缺口） |
| **议价能力指数** | 方案只给结论"议价能力低"，无可观测代理（无同 SKU 市场基准价） | **拒绝**，要客户给基准价来源 |
| **毛利率的成本构成**（材料/人工/制造费用） | `order_lines` 只有毛利额/率，无 BOM 成本结构 | **拒绝**，补 `bom_costs` 才能答 |
| **产能利用率的复算** | `utilization` 是方案输入，库里无班次工时/停机数据 | **可查询但标注"不可复算"** |
| **整体交付率作为考核** | 能算，但 §十列为范围外 | **可算、标"范围外"**（不是拒绝，避免把决策说成数据缺口） |
| **个人提成金额 / 绩效奖金** | 薪酬数据不进库（`commission_factor` 只记规则应用） | **拒绝**（§九之外的敏感域） |
| **"新客成交额"考核** | §十范围外；`leads`/orders 能算成交额，但不作为考核 | **可算、标"范围外"** |
| **裁员降本的量化** | 只有 `leave_reason`，没有裁撤成本模型 | **部分**：可算"是否有裁员"，不可算"裁员能省多少" |

---

## 五、建库后必须一次全绿的验收（14 条，见 `ebl_ops.dataset.json`）

1. FY2026 营收 11.0 亿（±0.5%） 2. FY2025 营收 9.0 亿（±0.5%） 3. 季度 2.5/2.7/2.9/2.9（±3%）
4. FY 加权毛利 ∈[18,19] 5. 每季加权毛利 ≥17 6. 低毛利营收占比 ≤25% 7. 低毛利订单在 ≥70% 产线上 = 0 条
8. 三档毛利落在区间（差异化/标准/低毛利/微改良） 9. 认证溢价 ∈[2,3] 且只挂微改良 10. 增长三桶区间
11. 核心客户流失 ≤2 12. headcount=2800 且 6 部门 13. 利用率<70% 与低毛利订单一一对应（双向） 14. `Σorder_lines.revenue = Σorders.revenue ± order_adjustments`

> 这 14 条绿了，才说明"表里的数和方案里的话是同一件事"；然后本体在上面声明指标，才有东西可编译。
