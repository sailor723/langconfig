# clinic 本体 · 阶段 9：拒绝清单与指标目录

数据源：`01-structure.ttl` + `02-meaning.ttl` + `metrics_ext.ttl`（同一张图）；实测值来自 `other/truth_values.json`，由独立手写 SQL 得出，与本体计算路径互不依赖。
本文件所有表格均由 `other/render_phase9.py` 从图里生成，没有一个数字是手打的。

## 0. 三句话

1. **28 个指标全部结构合格**，`6/6` 变异测试通过——删 grain、删 references、公理与谓词并存、universe 挂错颗粒、维度缺 domain，五种破坏全部被拒绝规则抓住。所以文中的『图内可判定拒绝 = 0』是**检查过**的 0，不是没检查的 0。
2. **15 个问题被业务口径挡住**，**10 个维度有数据却没有出口**。这两类才是这份清单的价值。
3. **最该补的缺口是时间**：28 个指标里**没有一个能按时间分组**。`:scheduledAt` / `:issuedAt` 在属性层是齐的（有 domain、有物理列），缺的只是指标上的一个 `:groupBy`——一个声明缺口，不是数据缺口。报『收入趋势』现在会被拒，补上才可答。

## 1. 指标目录

口径六件套：**颗粒**（在哪张表的行上数）→ **总体**（在谁的集合里数）→ **判定类**（哪些行算）→ **算法** → **公式**（逐行表达式）→ **实测值**（独立 SQL）。

> `ratio_of_sums` = 先各自求和再相除，永不逐行算比再平均；比率必带 `:numerator` / `:denominator`。

### 1.1 颗粒 = `:Appointment`（预约，8 个）

| 指标名 | 中文名 | 定义（第一句） | 判定类 | 算法 / 分组 / 公式 | 实测值 |
|---|---|---|---|---|---|
| `:appointments` | 预约数 | 已排程的预约条数，实测 5,418。 | 全部 | `count` | 5,418 |
| `:appointmentsByDoctorSpecialty` | 按医生专科预约数 | 按医生专科分组的预约数。 | 全部 | `count` · 按 `:specialty`（1 跳） | 4 组：皮肤科 2,111 / 儿科 1,644 / 全科 1,396 / 骨科 267 |
| `:appointmentsByStatus` | 按状态预约数 | 按状态分组的预约数。 | 全部 | `count` · 按 `:appointmentStatus`（0 跳） | 3 组：completed 3,236 / cancelled 1,105 / no_show 1,077 |
| `:cancellationRate` | 取消率 | 取消数 / 全部已排程预约 = 1,105 / 5,418 = 20.39%。 | 全部 | `ratio_of_sums` · `:cancelledAppointments` ÷ `:appointments` | 20.39% |
| `:cancelledAppointments` | 取消数 | 提前取消的预约，实测 1,105。 | `:CancelledAppointment` | `count` | 1,105 |
| `:completedAppointments` | 完成就诊数 | 真正发生的服务次数，实测 3,236（59.73%）。 | `:CompletedAppointment` | `count` | 3,236 |
| `:noShowAppointments` | 爽约数 | 病人没到的预约，实测 1,077。 | `:NoShowAppointment` | `count` | 1,077 |
| `:noShowRate` | 爽约率 | 爽约数 / 全部已排程预约 = 1,077 / 5,418 = 19.88%。 | 全部 | `ratio_of_sums` · `:noShowAppointments` ÷ `:appointments` | 19.88% |

### 1.2 颗粒 = `:TreatmentLine`（收费行，8 个）

| 指标名 | 中文名 | 定义（第一句） | 判定类 | 算法 / 分组 / 公式 | 实测值 |
|---|---|---|---|---|---|
| `:deepDiscountLineShare` | 深度折扣行占比 | 深度折扣行 / 全部收费行 = 1,083 / 6,443 = 16.81%。 | 全部 | `ratio_of_sums` · `:deepDiscountLines` ÷ `:treatmentLines` | 16.81% |
| `:deepDiscountLines` | 深度折扣行数 | 折扣率 ≥ 20% 的收费行，实测 1,083（16.81%）。 | `:DeepDiscountLine` | `count` | 1,083 |
| `:discountGiven` | 让价金额 | 按 数量 × 单价 × 折扣率 求和，实测 71,458.00 元。 | 全部 | `sum` · `qty * unit_price * discount` | 71,458.00 元 |
| `:discountedLines` | 打折行数 | 折扣率大于 0 的收费行，实测 2,152（33.40%）。 | `:DiscountedLine` | `count` | 2,152 |
| `:lineRevenue` | 按收费行算的诊疗收入 | 按 数量 × 单价 × (1 - 折扣率) 逐行算再求和，实测 1,353,412.00 元，与 :invoiceRevenue 完全相等 —— 这是本本体唯一的跨表对账（两条独立路径）。 | 全部 | `sum` · `qty * unit_price * (1 - discount)` | 1,353,412.00 元 |
| `:revenueByPatientCity` | 按患者城市收入 | 按收费行算收入，按患者所在城市分组。 | 全部 | `sum` · 按 `:city`（2 跳） · `qty * unit_price * (1 - discount)` | 4 组：无锡 361,352.00 / 上海 356,874.00 / 苏州 343,907.00 / 杭州 291,279.00 元 |
| `:revenueByTreatment` | 按项目收入 | 按收费行算收入，按诊疗项目名分组。 | 全部 | `sum` · 按 `:treatmentName`（1 跳） · `qty * unit_price * (1 - discount)` | 7 组：X光 403,312.00 / 输液 274,356.00 / 慢病随访 230,415.00 / 感冒问诊 180,288.00 元 … |
| `:treatmentLines` | 收费行数 | 收费明细行数，实测 6,443。 | 全部 | `count` | 6,443 |

### 1.3 颗粒 = `:Invoice`（发票，4 个）

| 指标名 | 中文名 | 定义（第一句） | 判定类 | 算法 / 分组 / 公式 | 实测值 |
|---|---|---|---|---|---|
| `:collectionRate` | 回款率 | 实收 / 开票 = 756,089.20 / 1,353,412.00 = 55.87%。 | 全部 | `ratio_of_sums` · `:collectedRevenue` ÷ `:invoiceRevenue` | 55.87% |
| `:highValueInvoices` | 高额发票张数 | 金额 ≥ 1,000 元的发票张数，实测 51。 | `:HighValueInvoice` | `count` | 51 |
| `:invoiceRevenue` | 开票收入 | 发票开出金额合计，实测 1,353,412.00 元。 | 全部 | `sum` · `total` | 1,353,412.00 元 |
| `:revenuePerCompletedVisit` | 每次就诊收入 | 开票收入 / 完成就诊数 = 1,353,412.00 / 3,236 = 418.24 元。 | 全部 | `ratio_of_sums` · `:invoiceRevenue` ÷ `:completedAppointments` | 418.24 元 |

### 1.4 颗粒 = `:Claim`（理赔，7 个）

| 指标名 | 中文名 | 定义（第一句） | 判定类 | 算法 / 分组 / 公式 | 实测值 |
|---|---|---|---|---|---|
| `:claimDecisionDays` | 平均理赔裁决天数 | 已裁决理赔从提交到裁决的平均天数，实测 10.60 天（最短 1 天、最长 20 天）。 | `:DecidedClaim` | `avg` · `EXTRACT(EPOCH FROM (decided_at - filed_at)) / 86400.0` | 10.60 天 |
| `:claims` | 理赔笔数 | 提交给保险公司的理赔笔数，实测 1,934，对应 1,934 张不同发票（本库一张发票最多一笔理赔，所以按笔和按发票同一个数）。 | 全部 | `count` | 1,934 |
| `:decidedClaims` | 已裁决理赔笔数 | 已出裁决结果的理赔，实测 1,292（679 核准 + 613 拒赔）。 | `:DecidedClaim` | `count` | 1,292 |
| `:pendingClaimRate` | 理赔待决率 | 待决 / 全部理赔 = 642 / 1,934 = 33.20%。 | 全部 | `ratio_of_sums` · `:pendingClaims` ÷ `:claims` | 33.20% |
| `:pendingClaims` | 待决理赔笔数 | 还没有裁决结果的理赔，实测 642（33.20%）。 | `:PendingClaim` | `count` | 642 |
| `:rejectedClaims` | 拒赔笔数 | 被拒赔的理赔，实测 613。 | `:RejectedClaim` | `count` | 613 |
| `:rejectionRate` | 拒赔率 | 拒赔笔数 / 已裁决理赔 = 613 / 1,292 = 47.45%。 | 全部 | `ratio_of_sums` · `:rejectedClaims` ÷ `:decidedClaims` | 47.45% |

### 1.5 颗粒 = `:Payment`（回款，1 个）

| 指标名 | 中文名 | 定义（第一句） | 判定类 | 算法 / 分组 / 公式 | 实测值 |
|---|---|---|---|---|---|
| `:collectedRevenue` | 实收金额 | payments 表里的实际收款合计，实测 756,089.20 元。 | 全部 | `sum` · `amount` | 756,089.20 元 |

### 1.6 公式与路径：口径里最容易写错的地方

| 指标 | 颗粒 | 公式 | 为什么必须这么写 |
|---|---|---|---|
| `:invoiceRevenue` | `:Invoice` | `total` | 走发票表；必须与 :lineRevenue 相等，这是跨表对账锚点 |
| `:lineRevenue` | `:TreatmentLine` | `qty * unit_price * (1 - discount)` | 走收费行，与发票表独立算出同一金额 |
| `:discountGiven` | `:TreatmentLine` | `qty * unit_price * discount` | 第三条独立路径：原价 1,424,870.00 = 净额 1,353,412.00 + 让价 71,458.00 |
| `:collectedRevenue` | `:Payment` | `amount` | 只有付款表代表钱到账；invoices.status 不代表（见 C 类） |
| `:claimDecisionDays` | `:Claim` | `(decided_at - filed_at) / 86400.0` | `:where :DecidedClaim` 显式排除 642 笔待决，不靠 AVG 静默跳过 NULL |
| `:revenueByPatientCity` | `:TreatmentLine` | `qty * unit_price * (1 - discount)` 按 `:city` | 两跳三表：收费行 → 预约 → 患者，路径由 `:references` 决定 |
| `:revenueByTreatment` | `:TreatmentLine` | 同上 按 `:treatmentName` | 一跳：收费行 → 项目 |
| `:appointmentsByDoctorSpecialty` | `:Appointment` | count 按 `:specialty` | 一跳：预约 → 医生 |

**跨颗粒比率的强制写法**（`:collectionRate`、`:revenuePerCompletedVisit`）：两条独立扫描再相除，
绝不 join 后逐行算。本库恰好每张发票 ≤1 笔回款，所以逐行算法会**侥幸不出错**——
这正是口径必须写死在图里、而不是留在人脑里的原因。实测 55.87% / 418.24 元。

## 2. 拒绝清单

### 2.1 三类拒绝，严重程度完全不同

| 类 | 数量 | 谁触发 | 意思 | 谁来解决 |
|---|---|---|---|---|
| **A 图内可判定** | 0 | 检查器 | 本体自己写错了（缺 grain / 缺路径 / 公理与谓词并存） | 我，当场 |
| **B 能力缺口** | 10 | 提问时 | 数据里有这个维度，但没有指标声明按它分组 | 加一条 `:groupBy` |
| **C 业务裁决** | 15 | 提问时 | 数据或口径本身不支持，硬算得到**看似合理的错数** | 业务 |

### 2.2 A 类 = 0，以及证明这个 0 不是空话

| 把图弄坏的方式 | 期望被拒 | 结果 |
|---|---|---|
| 删掉 :invoiceRevenue 的 :grain | `NO_GRAIN on invoiceRevenue` | PASS |
| 删掉 appointmentOfLine 的 :references | `NO_PATH on revenueByPatientCity` | PASS |
| 给 :CompletedAppointment 再加 :physicalPredicate | `AMBIGUOUS on completedAppointments` | PASS |
| 删掉 :PendingClaim 的 :physicalPredicate | `NO_AXIOM on pendingClaims` | PASS |
| 把 :deepDiscountLines 的 :universe 改成 :Invoice | `UNIVERSE_GRAIN on deepDiscountLines` | PASS |
| 删掉 :city 的 rdfs:domain | `NO_PATH on revenueByPatientCity` | PASS |

**6/6 全部触发。** 这 28 个指标现在能答，是因为它们真的写全了，不是因为检查器不会拒绝。

### 2.3 B 类：能力缺口 —— 10 条（补的都是 10 分钟的事，或者禁区）

| 维度 | 库里的列 | 本体状态 | 问它会怎样 |
|---|---|---|---|
| `:insurancePlan` | `patients.insurance_plan` | DECLARED_PROPERTY | 三值（自费 / 城镇医保 / 商业保险）。**只能用于就诊与收入侧**，理赔侧用不了（见 C 类 claimStatsByInsurancePlan）。 |
| `:birthYear` | `patients.birth_year` | DECLARED_PROPERTY | 只有出生年，年龄天生 ±1 岁误差，且必须绑定参照日（就诊日 or 今天）。 |
| `:doctorName` | `doctors.name` | DECLARED_PROPERTY | 路径存在（收费行→预约→医生），能算。但『按医生看收入』要先说清是开单医生还是执行医生——本库只有执行医生。 |
| `:listPrice` | `treatments.list_price` | DECLARED_PROPERTY | 挂牌价，不是收入（收入是行上的 unit_price）。拿它求和会得到一张从未发生过的账单。 |
| `:insurer` | `claims.insurer` | DECLARED_PROPERTY | 可答（A保险 963 / B保险 971），但**不能解释成险种差异**：两家拒赔率 48.57% vs 46.37% 几乎相同，说明不是风险差异。 |
| `:decision` | `claims.decision` | DECLARED_PROPERTY | 已用 `:where` 表达成核准 / 拒赔 / 待决三个类。再按 decision 分组是重复建模，故意不加。 |
| `:paymentMethod` | `payments.method` | DECLARED_PROPERTY | 三值清楚：微信 272,799.50 / 医保结算 246,862.20 / 现金 236,427.50 元。属于纯缺口，可直接补。 |
| `:invoiceStatus` | `invoices.status` | DECLARED_PROPERTY | **不是缺口，是禁区。** status 与 payments 互相矛盾（653 张 paid 无回款、694 张 unpaid 有回款），只能用付款表判断收款。 |
| `:scheduledAt(月/周/日)` | `appointments.scheduled_at` | DECLARED_PROPERTY | backlog 第一。预约时间 2026-07-10 ~ 2026-11-06，全库没有任何时间分组指标，趋势类问题全军覆没。 |
| `:issuedAt(月/周/日)` | `invoices.issued_at` | DECLARED_PROPERTY | 收入侧的时间轴。补的时候首尾残月必须标注（7 月只有 21 天、11 月只有 6 天）。 |

### 2.4 C 类：业务裁决 —— 15 条（这份清单就是和业务谈判的议程）

每条：问什么 → 为什么拒 → 实测证据 → 什么条件能开 → 现在给什么替代答案。

#### 1. `:claimStatsByInsurancePlan` — 不同医保类型的拒赔率分别是多少？

**数据自相矛盾**

- **为什么拒**：claims.insurer 与 patients.insurance_plan 是两套互不相干的值：insurer 只有 A保险/B保险 两个值，且在任何险种下都近似五五分。『自费』身份与『有保险理赔』直接矛盾。
- **证据**：214 名标注为『自费』的患者身上挂着 694 笔理赔（349 笔 A保险 + 345 笔 B保险），裁决结果分布与其他险种无异。商业保险 643 笔、城镇医保 597 笔，三个险种的理赔笔数也不按险种规模分布。调和它需要付款方台账，本库没有。
- **解锁条件**：新增付款方/险种台账，或业务确认 claims.insurer 的权威性并回填 patients。
- **现在能给的**：理赔一律独立统计，不按患者险种拆；按 insurer 拆理赔笔数可以（A保险 963 / B保险 971），但不把它解释成『险种差异』。

#### 2. `:highValueInvoiceAsRevenue` — 高额发票贡献了多少收入？

**阈值待业务认领**

- **为什么拒**：:HighValueInvoice 的 1,000 元这条线是我提的、不是业务定的（PENDING_BUSINESS_CONFIRMATION），而阈值一动名单规模差 4 倍，所以这个类只能挑催收名单，不能进任何收入口径。
- **证据**：≥800 有 238 张、≥1,000 有 51 张、≥1,200 有 6 张、≥1,500 有 1 张。发票金额 p50=392.50、p95=844.50、max=1,508.00，分布连续无断点 —— 1000 是 p95 向上取整，不是数据里的自然分界。
- **解锁条件**：业务认领这条线（或给出另一条），进 :thresholdSource 后才可以进汇报口径。
- **现在能给的**：只给张数（51 张，占 1.6%）作为名单入口，不给『高额发票收入占比』。

#### 3. `:repeatVisitRate` — 复诊率多少？患者留存怎么样？

**没有口径**

- **为什么拒**：『复诊』需要业务定义窗口（30 天内再来算不算？同一项目还是任意项目？取消的算不算？）。可以算，但现在算出来的任何一个数都是我们替业务下的定义。
- **证据**：同一患者可用 appointments.patient_id 追踪，数据支持计算；缺的不是数据是口径。
- **解锁条件**：业务给出复诊窗口与判定条件。
- **现在能给的**：可以给『有 ≥2 次完成就诊的患者数』这类不带窗口的事实，但必须叫它原样，不叫复诊率。

#### 4. `:revenuePerPatient` — 人均消费多少？

**没有口径**

- **为什么拒**：分母有三种都说得通的选法：全部患者、有预约的患者、有完成就诊的患者。三者差很大，选哪个是口径不是技术。
- **证据**：患者总数、有预约患者数、有完成就诊患者数三个分母不同（本库患者可重复预约），任何一个都不比其他两个『更对』。
- **解锁条件**：业务指定分母。
- **现在能给的**：已声明 :revenuePerCompletedVisit = 418.24 元（分母是完成就诊数，不是患者数），问『人均』时要指出这差别。

#### 5. `:outstandingReceivable` — 应收余额还有多少？哪些发票还欠钱？

**没有颗粒**

- **为什么拒**：开票额在 Invoice 颗粒、回款额在 Payment 颗粒，两者相减得到的数不属于任何一个颗粒；要声明它必须先定账龄基准日和『部分回款如何归属』，这两件事业务没给。
- **证据**：差额 = 1,353,412.00 - 756,089.20 = 597,322.80 元。有余额发票 2,426 张：完全未收款 897 张（374,410.00）、部分收款 1,529 张（补差 222,912.80）、恰好收齐 810 张、超额收款 0 张。实测 0 张发票有超过 1 笔回款 —— 所以逐张余额技术上算得出来，但需要一种『以 Invoice 为颗粒、formula 能内嵌子查询』的指标类型，本编译层没有。
- **解锁条件**：业务给出账龄基准日 + 部分回款的归属规则，并允许新增一种带子查询的发票级指标类型。
- **现在能给的**：只说差额 597,322.80 元，且明确标注『本报告口径下的差额』，不叫应收余额。

#### 6. `:paidInvoiceRate` — 已收款发票占比多少？未付款比例多少？

**依据的列是错的**

- **为什么拒**：invoices.status 与 payments 表互相矛盾，用 status 算收款口径会给出一个自洽但错误的数。
- **证据**：status = paid 的 2,298 张里有 653 张完全没有回款行；status = unpaid 的 938 张里有 694 张实际收到过钱。两边的错误互相抵消一部分，所以『用 status 算』和『用 payments 算』的总额ratio 看起来都像样 —— 这是它危险的地方。
- **解锁条件**：数据治理：让 invoices.status 由 payments 派生（或明确 status 的真实语义）。
- **现在能给的**：回款一律走 payments：:collectedRevenue = 756,089.20，:collectionRate = 55.87%。

#### 7. `:startedAtBucketing` — 按实际开始时间看就诊时段分布／平均候诊时长

**字段不可用**

- **为什么拒**：appointments.started_at 对 2,182 行恒为 NULL，任何以它为时间轴或做减法的指标都会静默丢掉 40% 的预约。
- **证据**：5,418 行中 2,182 行为 NULL（40.27%）；非 NULL 部分没有规律。候诊时长还需要 arrived_at，本库没有。
- **解锁条件**：回填 started_at；或明确它只对已完成预约有值，并把口径限在完成就诊内。
- **现在能给的**：时间轴一律用 :scheduledAt（全部状态都有值）。

#### 8. `:slowClaimRate` — 有多少理赔超期了？超期率多少？

**阈值没有来源**

- **为什么拒**：本库没有承诺时效字段，裁决时长分布近乎均匀，没有断点 —— 任何 N 天都是凭空划的线。
- **证据**：已裁决 1,292 笔裁决时长 1–20 天，按 2 天分箱每箱 106–137 笔（1–2 天 134 笔，19–20 天也是 134 笔）。取 10 天还是 15 天，超期率会差一倍以上，且两个数都『看起来合理』。
- **解锁条件**：业务给出承诺理赔时效（如『15 个工作日内裁决』），阈值进 :thresholdSource 并只写一处。
- **现在能给的**：:claimDecisionDays = 10.60 天（只说事实，不说好坏）。

#### 9. `:grossMargin` — 毛利多少？利润率多少？哪个项目最赚钱？

**没有成本数据**

- **为什么拒**：全库没有任何成本数据：treatments 只有 list_price（挂牌价），没有耗材/人力/分摊成本。
- **证据**：treatments 列：code, name, list_price。8 张表里没有 cost 类表。
- **解锁条件**：导入项目成本与人力成本。
- **现在能给的**：只能给收入侧：按项目收入（X光 403,312 / 输液 274,356 / 慢病随访 230,415 / 感冒问诊 180,288），以及让价（71,458）。收入高 ≠ 赚钱。

#### 10. `:doctorUtilization` — 各科医生的产能利用率是多少？空档率多少？

**没有分母**

- **为什么拒**：全库只有 8 张表，没有任何班表/可约时段表。拿预约数当分母是循环论证。
- **证据**：treatments / doctors / patients / appointments / invoices / treatment_lines / payments / claims —— 无 capacity、无 schedule。
- **解锁条件**：新增医生排班表（医生 × 时段 × 可约容量）。
- **现在能给的**：给绝对量：按专科预约数（皮肤科 2,111 / 儿科 1,644 / 全科 1,396 / 骨科 267），不除任何东西。

#### 11. `:yoyGrowth` — 今年比去年增长多少？

**没有对照窗口**

- **为什么拒**：数据只有单一 120 天窗口，没有任何去年同期数据。
- **证据**：预约 2026-07-10 ~ 2026-11-06；发票 2026-07-10 ~ 2026-11-06（5 个月，首尾不完整）；db now = 2026-11-06。
- **解锁条件**：导入上一年的数据。
- **现在能给的**：同比一律拒绝；环比可以按 :scheduledAt 自建窗口，但必须标注 2026-07 与 2026-11 是不完整月。

#### 12. `:reimbursedAmount` — 保险核减了多少钱？赔付了多少？

**字段不存在**

- **为什么拒**：claims 只有 decision（approved / rejected），没有赔付金额，也没有核减额。
- **证据**：claims 列：id, invoice_id, insurer, filed_at, decided_at, decision。要算核减必须知道申请额与核准额，两个都没有。
- **解锁条件**：新增 claimed_amount / approved_amount 两列。
- **现在能给的**：只能回答『拒了几笔』（613 笔）和『核准几笔』（679 笔），不能回答『少收多少钱』。

#### 13. `:receivableAging` — 应收账龄分布？逾期 30 / 60 / 90 天各多少？

**字段不存在**

- **为什么拒**：invoices 没有 due_date、也没有账期约定字段，『逾期』无参照。
- **证据**：invoices 列：id, appointment_id, issued_at, total, status。
- **解锁条件**：新增 due_date 或账期规则（且要先解决 status 矛盾，见 :paidInvoiceRate）。
- **现在能给的**：只能按 issued_at 算『开票后多久收到钱』（对有回款的发票），不叫账龄。

#### 14. `:exactAge` — 患者平均年龄多少？按年龄段看收入

**只能部分回答**

- **为什么拒**：只有 birth_year（出生年），没有出生日期。年龄最多精确到 ±1 岁，且必须绑定一个参照日（就诊日 or 今天）。
- **证据**：patients 列：id, name, birth_year, city, insurance_plan。
- **解锁条件**：把出生日期补进来；或业务接受按出生年分组的粗口径并声明参照日。
- **现在能给的**：可以按 birth_year 分组，或给『粗年龄带』（±1 岁），但必须在答案里写清参照日与误差。

#### 15. `:monthAsTrend` — 11 月收入掉了 80%，发生了什么？

**窗口首尾不完整**

- **为什么拒**：窗口首尾都不完整：数据从 2026-07-10 开始、到 2026-11-06 结束。7 月和 11 月都是残月，把它们与整月比就是伪趋势。
- **证据**：2026-07: 236,863（21 天）；08: 350,202；09: 349,743；10: 347,392；11: 69,212（6 天）。9–10 月几乎持平，11 月的『暴跌』是窗口边界不是业务变化。
- **解锁条件**：补全 7 月 1–9 日与 11 月 7–30 日的数据。
- **现在能给的**：可以给月度收入，但必须把 7 月和 11 月标成不完整月；结论只能用 8–10 月那三个完整月。

## 3. 汇总

| | |
|---|---|
| 结构合格、现在就能答的指标 | **28** |
| 其中带 `:where` 判定类、口径无歧义的 | **10** |
| 图内可判定拒绝（本体自身缺陷） | **0** |
| 能力缺口（加 `:groupBy` 即可） | **10** |
| 业务裁决类拒绝 | **15** |
| 变异测试（拒绝规则本身的有效性） | **6/6 通过** |

按原因分布：没有口径 2 条；字段不存在 2 条；数据自相矛盾 1 条；阈值待业务认领 1 条；没有颗粒 1 条；依据的列是错的 1 条；字段不可用 1 条；阈值没有来源 1 条；没有成本数据 1 条；没有分母 1 条；没有对照窗口 1 条；只能部分回答 1 条；窗口首尾不完整 1 条。

## 4. 这张清单怎么用

1. **先补时间维度**（B 类第 9、10 条）。这一个动作把整个趋势家族从『拒答』变成『可答』，收益远大于其余九条之和。
2. **C 类前四条是硬伤，必须先和业务谈**：`paidInvoiceRate`（状态字段自相矛盾）、`claimStatsByInsurancePlan`（两套保险字段互不相通）、`startedAtBucketing`（时间字段 40% 为 NULL）、`highValueInvoiceAsRevenue`（1,000 元这条线是我提的，不是业务定的）。这四条不是能力问题，是事实问题——不问清楚，任何报表都可能在说谎。
3. **别把 B 类当 bug 修**：`paymentMethod`、`doctorName` 是纯缺口，补；`invoiceStatus`、`listPrice` 是禁区，**补了就是错**。清单把这两种情况分开，就是为了防止一刀切。

## 5. 还没做的（说清楚，免得被当成已完成）

- 阶段 6–8 的完整对账报告、守卫（guardrails）与查询编译验证，本文件只覆盖了指标级实测值，没有逐条走编译链路。
- 没有 UI / 语义层导出。按 skill 的顺序，门禁（gates）通过前不建 UI。
- 时间维度一旦补齐，`monthAsTrend` 这条拒绝可以部分解除，但残月标注规则要一起写进图里。
