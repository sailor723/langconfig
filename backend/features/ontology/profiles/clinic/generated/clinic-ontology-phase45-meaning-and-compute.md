# clinic 本体 · 阶段 4–5 交付说明（含义层 + 计算层）

数据库：`clinic_db`（PostgreSQL，db now = 2026-11-06）
本阶段产物：`02-meaning.ttl`（含义/公理，253 三元组）、`metrics_ext.ttl`（计算覆盖层，154 三元组）
自检：`other/verify_meaning.py` —— 全部检查通过（退出码 0），合并图共 643 三元组，可解析。

---

## 阶段 4 做了什么：把"什么意思"写成公理

ontology 里最容易骗人的不是 SQL，是没人写下来的口径。阶段 4 只做一件事：把每个名词的判定规则写成**一条且只有一条**可执行的公理，让同一张表上的两种身份不能同时成立。

| 决定 | 公理/机制 | 为什么必须是公理而不是 SQL |
|---|---|---|
| 服务是否发生 | `:CompletedAppointment ≡ Appointment ∧ status="completed"` 等三条 `owl:equivalentClass` | 取消、爽约、完成三档互斥且穷尽，任何"服务人次"都必须落在这三条之一 |
| 理赔是否有结论 | `:DecidedClaim` 用公理（`decision` 非空），`:PendingClaim` 用 `:physicalPredicate "decision IS NULL"` | `decision` 为空是**状态**不是缺失值。写成公理会被数据清洗当脏数据清掉，写成 predicate 才能保住 |
| 发票是否高额 | `:HighValueInvoice ≡ invoiceTotal ≥ 1000`（阈值带来源标注） | 阈值是业务变量，不能散落在 20 条 SQL 里 |

**阈值一共只允许 3 处**，每处都带 `:thresholdSource`：

1. `:DiscountedLine` 折扣率 > 0 —— 分布事实（`discount` 实际只取 0 / 0.1 / 0.2 / 0.3），不需要业务认领；
2. `:DeepDiscountLine` 折扣率 ≥ 0.2 —— 分布自然分档 + 一个明确的选择，两者都写在文件里；
3. `:HighValueInvoice` 发票金额 ≥ 1,000 —— **PENDING_BUSINESS_CONFIRMATION**，业务认领之前只作催收名单入口，不进任何考核口径。

**两条恒等式**（阶段 6 的对账锚点，不是装饰）：

- 跨表：`:invoiceRevenue = :lineRevenue = 1,353,412.00`（发票表 vs 收费行表，两条独立路径）；
- 表内：原价 1,424,870.00 = 诊疗收入 1,353,412.00 + 让价 71,458.00，残差 0.00。

**一个不可用的字段**：`appointments.started_at` 对 2,182 / 5,418 行（40.3%）恒为 NULL，所以本体里所有时间轴一律走 `:scheduledAt`，任何以 `started_at` 分桶的指标都是错的（见 REFUSED 第 8 条）。

---

## 阶段 5 做了什么：把"怎么算"隔离到覆盖层

计算全部放在 `metrics_ext.ttl`，与含义分层，原因只有一个：**改算法不应该能改到定义**。比率的三件套（分子/分母/倍数）留在 `02-meaning.ttl`，因为"谁的比谁"是含义不是算法；覆盖层只补 `:aggregate` / `:grain` / `:universe` / `:where` / `:groupBy` / `:formula`。同一个三元组不在两个文件里各写一遍 —— 那就是两个真相。

三条硬约束（阶段 6 的变异测试就照这三条打）：

1. 带 `:formula` 的指标必须有 `:grain`；
2. 每个指标必须有 `:universe`，且它只能是 `:grain` 本身或它的子类；
3. `:where` 只指向 `02` 里声明过的类，且该类只能有一种判定方式（公理 XOR `:physicalPredicate`），两边都写必须被拒绝。

比率一律 `ratio_of_sums`（先各自求和再相除），**永不逐行算比再平均**。`:collectionRate` 与 `:revenuePerCompletedVisit` 是跨颗粒比率（分子在 Payment/Invoice、分母在 Invoice/Appointment），编译器必须用两条独立扫描再相除；直接 join 后逐行算比会在"一发票多回款"时重复计分母（本库当前实测 0 张发票多笔回款，但约束照样要挂）。

### 28 个指标

| 指标 | 名称 | grain | where | 算法 | 实测真值 |
|---|---|---|---|---|---|
| `:appointments` | 预约数 | :Appointment | — | count | 5,418 |
| `:appointmentsByDoctorSpecialty` | 按医生专科预约数 | :Appointment | — | count · 按 :specialty | 见正文 |
| `:appointmentsByStatus` | 按状态预约数 | :Appointment | — | count · 按 :appointmentStatus | 见正文 |
| `:cancellationRate` | 取消率 | :Appointment | — | ratio_of_sums | 20.39% |
| `:cancelledAppointments` | 取消数 | :Appointment | :CancelledAppointment | count | 1,105 |
| `:completedAppointments` | 完成就诊数 | :Appointment | :CompletedAppointment | count | 3,236 |
| `:noShowAppointments` | 爽约数 | :Appointment | :NoShowAppointment | count | 1,077 |
| `:noShowRate` | 爽约率 | :Appointment | — | ratio_of_sums | 19.88% |
| `:claimDecisionDays` | 平均理赔裁决天数 | :Claim | :DecidedClaim | avg `EXTRACT(EPOCH FROM (decided_at - filed_at)) / 86400.0` | 10.60 |
| `:claims` | 理赔笔数 | :Claim | — | count | 1,934 |
| `:decidedClaims` | 已裁决理赔笔数 | :Claim | :DecidedClaim | count | 1,292 |
| `:pendingClaimRate` | 理赔待决率 | :Claim | — | ratio_of_sums | 33.20% |
| `:pendingClaims` | 待决理赔笔数 | :Claim | :PendingClaim | count | 642 |
| `:rejectedClaims` | 拒赔笔数 | :Claim | :RejectedClaim | count | 613 |
| `:rejectionRate` | 拒赔率 | :Claim | — | ratio_of_sums | 47.45% |
| `:collectionRate` | 回款率 | :Invoice | — | ratio_of_sums | 55.87% |
| `:highValueInvoices` | 高额发票张数 | :Invoice | :HighValueInvoice | count | 51 |
| `:invoiceRevenue` | 开票收入 | :Invoice | — | sum `total` | 1,353,412.00 |
| `:revenuePerCompletedVisit` | 每次就诊收入 | :Invoice | — | ratio_of_sums | 418.24 |
| `:collectedRevenue` | 实收金额 | :Payment | — | sum `amount` | 756,089.20 |
| `:deepDiscountLineShare` | 深度折扣行占比 | :TreatmentLine | — | ratio_of_sums | 16.81% |
| `:deepDiscountLines` | 深度折扣行数 | :TreatmentLine | :DeepDiscountLine | count | 1,083 |
| `:discountGiven` | 让价金额 | :TreatmentLine | — | sum `qty * unit_price * discount` | 71,458.00 |
| `:discountedLines` | 打折行数 | :TreatmentLine | :DiscountedLine | count | 2,152 |
| `:lineRevenue` | 按收费行算的诊疗收入 | :TreatmentLine | — | sum `qty * unit_price * (1 - discount)` | 1,353,412.00 |
| `:revenueByPatientCity` | 按患者城市收入 | :TreatmentLine | — | sum `qty * unit_price * (1 - discount)` · 按 :city | 见正文 |
| `:revenueByTreatment` | 按项目收入 | :TreatmentLine | — | sum `qty * unit_price * (1 - discount)` · 按 :treatmentName | 见正文 |
| `:treatmentLines` | 收费行数 | :TreatmentLine | — | count | 6,443 |

分组指标的实测值（本次全库跑出，作为阶段 6 的对照物，已存 `other/truth_values.json`）：

- `:appointmentsByStatus`：completed 3,236（59.73%）、cancelled 1,105（20.39%）、no_show 1,077（19.88%），三档之和 = 5,418 ✔
- `:revenueByPatientCity`：无锡 361,352.00、上海 356,874.00、苏州 343,907.00、杭州 291,279.00，四城之和 = 1,353,412.00 ✔
- `:revenueByTreatment`：X光 403,312、输液 274,356、慢病随访 230,415、感冒问诊 180,288、换药 140,049、血常规 124,992 ✔
- `:appointmentsByDoctorSpecialty`：按 `doctors.specialty` 分组，经 预约 → 医生 一跳

---

## 自检结果（编译器不在本工作区，先机器判能判的）

`other/verify_meaning.py` 判 18 项，全部 PASS：

| 检查 | 结果 |
|---|---|
| 18 个派生类，无一个同时拥有公理和 `:physicalPredicate` | PASS |
| 未定义的基类都有 `:physicalTable` | PASS |
| 阈值共 3 处，每处都有可判定的 `:thresholdSource` | PASS |
| `02` 与 `metrics_ext` 声明的指标集合完全一致（各 28 个） | PASS |
| 每个指标都有 `rdfs:label` + `:businessDescription` | PASS |
| 每个指标都有 `:grain` 与 `:universe` | PASS |
| 7 个比率都有分子分母，且分子分母都是已声明指标 | PASS |
| 9 个 `:where` 全部指向 `02` 里声明过的类 | PASS |
| `:formula` 里 7 处裸标识符全是 grain 表的真实列 | PASS |
| 4 个 `:groupBy` 维度从对应 grain 可达（0/1/1/2 跳） | PASS |

另做了一次与文档无关的独立核对：28 个指标的实测值用**生 SQL 直接算一遍**（`other/truth_values.py`），与写进 `:businessDescription` 的数字逐条比对，全部一致；比对过程中修掉了三处口算出错的数字（应收差额对应发票张数、裁决时长分布尾端、自费患者理赔笔数）。

---

## 刻意不声明的 8 个指标（REFUSED 预演）

拒绝分三类：**没有分母**、**没有口径**、**数据自相矛盾**。完整理由写在 `metrics_ext.ttl` 第九节，这里只列清单：

| 拒绝的指标 | 类型 | 一句话理由 |
|---|---|---|
| `:outstandingReceivable` 应收余额 | 没有粒度 | 跨颗粒差，2,426 张发票有余额；需要子查询型指标，本编译层没有 |
| `:slowClaimRate` 超期理赔率 | 没有口径 | 裁决时长 1–20 天近乎均匀（每个 2 天区间 106–137 笔），没有断点 |
| `:doctorUtilization` 医生产能利用率 | 没有分母 | 库里只有预约结果，没有班表/可约时段 |
| `:selfPayClaimRate` 按险种拆理赔 | 数据矛盾 | 保险计划为"自费"的 214 名患者挂了 694 笔理赔 |
| `:yoyGrowth` 同比 | 没有口径 | 数据只有单一 120 天窗口（2026-07-10 ~ 2026-11-06） |
| `:paidInvoiceRate` 已收款发票占比 | 依据错列 | `invoices.status` 与 `payments` 互相矛盾 |
| `:reimbursedAmount` 核减金额 | 字段不存在 | `claims` 只有 decision，没有金额 |
| `started_at` 时间分桶 | 字段不可用 | 40.3% 恒 NULL，会静默丢行 |

---

## 下一步（阶段 6，未做）

1. 变异测试：删 `:grain`、删一处 `:references`、把 `:noShowRate` 分母改成不含取消 —— 三种变异必须被拒绝或给出不同且可解释的数；
2. 双路对账门禁：`:invoiceRevenue` vs `:lineRevenue`、`:discountGiven` 两种算法、`:appointmentsByStatus` 三档求和；
3. 只有以上全绿，才允许进入重述层（阶段 7）与展示层。

**没有编译器**这件事必须说清楚：本阶段交付的是"人可读、机器可解析、口径有出处"的本体文件与真值对照表，`verify_meaning.py` 只能证明文件自洽与数值正确，不能证明工程链路能跑通。真正跑编译需要 `$(PROFILE)` 的 ontology_dir + overlay 与 `validate-sql` —— 这两样在本工作区里不存在，所以我没有假装跑过。
