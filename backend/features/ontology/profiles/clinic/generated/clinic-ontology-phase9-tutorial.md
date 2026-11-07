# 门诊收费与理赔本体 · 阶段 9（教程）

工作区：`/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/outputs/users/1/agents/agent_348`（admin 的账号树）

## 交付物

| 文件 | 用途 |
|---|---|
| `tutorial.json` | 工作台读的教程（`tutorial_api.authored` 固定读 profile 旁边的 `tutorial.json`） |
| `other/check_tutorial.py` | 教程四条闸门的自检脚本，走 `tutorial_api.py --mode steps/run/definition` 同一代码路径 |
| `other/probe_plan_rows.py`、`other/probe_plan_budget.py`、`other/probe_plan_budget2.py` | 排查护栏 plan budget 的探针（见"发现"） |
| `clinic_settings.json` | 阶段上游留下的 profile，本次未改（`features` 逐字照抄工作台给定值） |

`tutorial.json` 里 27 个 `items[]` 名字全部是图里已声明的对象 / 定义类 / 指标：8 个对象、10 个定义类、28 个指标（27 编译 + 1 按名拒绝）。正文不写指标数值 —— 数字由 `/api/tutorial/run` 现场从库里跑出来，避免文档与数据漂移。

## 九步，按读者问问题的顺序

| # | kind | 标题 | items |
|---|---|---|---|
| 1 | objects | 一行是什么：先定颗粒 | Appointment, TreatmentLine, Invoice, Claim |
| 2 | definitions | 「完成」「爽约」「取消」「待决」指哪些行 | CompletedAppointment, NoShowAppointment, CancelledAppointment, PendingClaim, DecidedClaim |
| 3 | definitions | 阈值只写一处，并说清线哪来的 | DiscountedLine, DeepDiscountLine, HighValueInvoice |
| 4 | metrics | 先数数 | appointments, completedAppointments, pendingClaims |
| 5 | metrics | 比率：先说清分子分母 | noShowRate, cancellationRate, rejectionRate, collectionRate |
| 6 | metrics | 钱：开票、实收、让价是三件事 | invoiceRevenue, lineRevenue, collectedRevenue, discountGiven |
| 7 | metrics | 分维度：路径写在关系上 | revenueByPatientCity, revenueByTreatment, appointmentsByDoctorSpecialty |
| 8 | refusals | 答不了的也说出来：按名拒绝 | claimDecisionDays |
| 9 | guard | 护栏：一个问题最多能花多少 | （无） |

## 四条教程闸门（实测输出）

```
图里已声明：8 个对象、10 个定义类、28 个指标
  [PASS] tutorial.steps_resolve — source='profile', steps=9, items=27, 未声明的名字=无
  [PASS] tutorial.metric_runs — 14/14 跑通；
         appointments=5418 plan_rows=5418、completedAppointments=3236 plan_rows=3236、
         pendingClaims=642 plan_rows=642、noShowRate=19.878… plan_rows=5418、
         cancellationRate=20.395… plan_rows=5418、rejectionRate=47.446… plan_rows=1077、
         collectionRate=55.865… plan_rows=3236、invoiceRevenue=1353412.0 plan_rows=3236、
         lineRevenue=1353412.0 plan_rows=0、collectedRevenue=756089.2 plan_rows=2339、
         discountGiven=71458.0 plan_rows=0、revenueByPatientCity=无锡 plan_rows=5418、
         revenueByTreatment=X光 plan_rows=0、appointmentsByDoctorSpecialty=皮肤科 plan_rows=5418
  [PASS] tutorial.definition_rows — 8/8 选中非零行；CompletedAppointment=3236、NoShowAppointment=1077、
         CancelledAppointment=1105、PendingClaim=642、DecidedClaim=1292、DiscountedLine=2152、
         DeepDiscountLine=1083、HighValueInvoice=51
  [PASS] tutorial.has_refusal — refusals 步骤=1，guard 步骤=1；
         claimDecisionDays: formula mentions 'epoch', which is not a column of :Claim or of any
         class reachable through declared relationships
闸门 4/4 PASS（exit 0）
```

`invoiceRevenue` 与 `lineRevenue` 两条独立路径同为 **1,353,412.0**，对账锚点成立。

## 其余闸门（宿主 `check_clinic.py --profile ./clinic_settings.json`）

```
C — ontology   C0/C1a/C1b/C1c PASS · C2a 编译 27、按名拒绝 1 · C2b 拒绝都带原因
               C3 truth：lineRevenue / invoiceRevenue / appointments / completedAppointments /
               noShowAppointments / collectionRate 各等于独立手写 SQL 路径 PASS
               C4a 删 :grain 拒绝 · C4b 删 :references 改变可答指标集 · C4c 拼错列名拒绝
               C4d 歧义列拒绝 · C4e 删定义公理后拒绝 · C5 无类同时带公理与 :physicalPredicate
R — reasoning  R1 10 个定义 · R2a 每个定义编译且选中非零行 · R2b 三档状态与独立列级查询行集相同
               R3a/R3b/R3c samples 13 条：7 答、6 按名拒绝
               R4a/R4b/R4c/R4d HermiT 推断成立、无不可满足类、删公理即失去推断
               [NOT RUN] R5 SPARQL 车道（Ontop/R2RML）—— 本数据集无 R2RML 映射，
                         features.lane_b=false，绿了就是谎
G — guardrails G1a big tables = appointments/invoices/claims/payments
               G1b 列表被 LIMIT 到 max_rows · G2 注入 90 天窗 · G3 计划超预算被拒绝
               G4a 已声明指标不加窗 · G4b 无界扫描只报告不改写 · G5 语句超时被中断（474 ms）
               G6 空窗被报告而不是静默返回 0
GATES PASS (with NOT RUN items)
```

## 发现（宿主护栏，不在本次改动范围）

`guard.plan_rows()` 只累加 **扫描节点**（`Relation Name` 命中 `big_tables` 的那些）的 `Plan Rows`，join / aggregate 顶节点的行数不计。两个后果，都已实测：

1. `treatment_lines`（6,443 行，本库最大的表）不在 `big_tables` 里 —— 它没有时间列，加了会让 `apply()` 的加窗逻辑没有列可用。于是收费行颗粒的查询 `plan_rows` 恒为 **0**：
   `lineRevenue plan_rows=0`、`discountGiven plan_rows=0`、`revenueByTreatment plan_rows=0`、未加窗的 `SELECT * FROM treatment_lines` 也是 0。
2. 更一般地，join 的规模只是把两侧扫描量取最大，不是乘积：
   `SELECT count(*) FROM treatment_lines a CROSS JOIN invoices b` 实际计划顶节点 **20,849,548** 行，护栏量到 **2,493** 行（预算 5,000,000）→ 放行，真跑到 **15,888,438** 对（309 ms）。
   这张表小所以不疼，但同样的量法在大 join 上会漏。

建议（改的是宿主 `retail_graph/guard.py`，我没有权限在工作区外写文件，故只报不改）：
把 `worst` 改成对 **所有节点** 取 `Plan Rows` 的最大值（或直接看根节点），并把"体量大但没有时间列"的表列进一个只用于计划预算的表清单 —— 加窗与"计划多少钱"本来就是两件事，现在被同一个 `big_tables` 字典捆住了。

现有的第二道网仍在：列表类查询一律 `LIMIT max_rows`，每条语句 8s `statement_timeout`（G5 实测 474 ms 中断）。

## 未做的事

- `features.tutorial` 是工作台给定的 `false`，按契约逐字照抄未改。要让 Tutorial 页签出现，需工作台侧置 `true` —— 属于宿主配置，不在本次范围。
- 未编造任何阈值、颗粒或指标；`HighValueInvoice` 的 1000 元仍是标注"待业务认领"的提案，只用于催收名单，不进任何收入口径。
