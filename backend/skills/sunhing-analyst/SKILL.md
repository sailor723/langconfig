---
name: sunhing-analyst
description: Sun Hing Vision Group transformation KPI tracker. KPI #1 — 协商减员完成率 (Severance Completion Rate).
tags: [sun-hing, transformation, restructuring, kpi, severance]
triggers:
  - When user says "减员", "severance", "KPI #1", "employee"
allowed-tools: [sqlite_execute, python_execute]
version: 1.0
author: system
---

## Schema

### 表：dim_kpi

| kpi_id | kpi_name | roe_factor | unit | target |
|---|---|---|---|---|
| 01_协商减员完成率 | 协商减员完成率 | 净利润率 | % | 100.0 |

### 表：fact_kpi_monthly

| period | kpi_id | actual | target | unit |
|---|---|---|---|---|
| e.g. '2026-09' | 01_协商减员完成率 | 0.0 | 100.0 | % |

### 表：raw_hr (aggregated headcount)

| period | total_headcount | production_headcount | severance_planned | severance_completed_cumulative | severance_paid_cumulative_wan |

### 表：raw_employee (individual employee detail)

| column | type | description |
|---|---|---|
| employee_code | TEXT | e.g. 'EMP-D0001' |
| factory | TEXT | 东莞 (650) / 河源 (206) |
| department | TEXT | e.g. 成型, 打磨, 抛光, 组装, 质检 |
| position_category | TEXT | Operator / Tech Lead / Team Lead |
| tenure_years | INTEGER | 1-35 years |
| is_severed | INTEGER | 0=retained, 1=severed |
| severance_month | TEXT | which month they were severed |
| compensation_wan | REAL | severance payment (万HKD) |
| has_dispute | INTEGER | 0=no, 1=yes (~2%) |
| satisfaction_score | REAL | 1-10 post-severance survey |
| converted_to_partner | INTEGER | 0=no, 1=yes (~40%) |

## KPI #1 定义

**协商减员完成率** — 856人 (东莞650 + 河源206) 已协商完成比例。

- **公式**: `(SELECT COUNT(*) FROM raw_employee WHERE is_severed=1) / 856 * 100%`
- **月度追踪**: `SELECT severance_month, COUNT(*) FROM raw_employee WHERE is_severed=1 GROUP BY severance_month`
- **成本追踪**: `SELECT SUM(compensation_wan) FROM raw_employee WHERE is_severed=1`
- **纠纷率**: `SELECT COUNT(*) FROM raw_employee WHERE has_dispute=1 / 810 * 100%`
- **目标**: 100% (3个月60%, 6个月90%)
- **预警**: <85%

### 关键查询

```sql
-- Monthly severance progress with cost
SELECT severance_month,
       COUNT(*) AS severed,
       ROUND(SUM(compensation_wan), 1) AS total_cost,
       ROUND(SUM(compensation_wan) / COUNT(*), 2) AS avg_cost
FROM raw_employee
WHERE is_severed=1
GROUP BY severance_month
ORDER BY severance_month;

-- Dispute employees detail
SELECT employee_code, factory, department, compensation_wan, satisfaction_score
FROM raw_employee
WHERE has_dispute=1
ORDER BY factory, department;

-- Partner conversion rate by factory
SELECT factory,
       COUNT(*) AS total,
       SUM(converted_to_partner) AS converted,
       ROUND(AVG(converted_to_partner) * 100, 1) AS conversion_pct
FROM raw_employee
WHERE is_severed=1
GROUP BY factory;
```

## KPI #02 定义: 历史人力成本追缴化解率

**Historical labor liability resolution rate** — 6,864万 historical liability (社保/公积金/年金/税务/其他) resolved via negotiation.

- **公式**: `(SUM(resolved_wan) / SUM(total_amount_wan)) × 100%` from `raw_liability`
- **目标**: ≥80% within 12 months
- **预警**: <60% at month 6
- **关键查询**:

```sql
-- Resolution by category
SELECT category, COUNT(*) AS items,
       ROUND(SUM(total_amount_wan), 0) AS total,
       ROUND(SUM(resolved_wan), 0) AS resolved,
       ROUND(SUM(remaining_wan), 0) AS remaining,
       ROUND(SUM(resolved_wan) / SUM(total_amount_wan) * 100, 1) AS pct
FROM raw_liability
GROUP BY category
ORDER BY remaining DESC;

-- High priority items still unresolved
SELECT item_code, category, description, authority, remaining_wan, resolution_method
FROM raw_liability
WHERE priority = '高' AND status != '已化解'
ORDER BY remaining_wan DESC;
```

### 表：raw_liability

| 列名 | 类型 | 描述 |
|---|---|---|
| item_code | TEXT | e.g. DG-SI-001 (东莞社保#1) |
| category | TEXT | 社保/公积金/企业年金/税务/劳动监察/其他 |
| description | TEXT | Item description |
| authority | TEXT | Government agency |
| total_amount_wan | REAL | Original liability amount (万HKD) |
| resolved_wan | REAL | Amount resolved |
| remaining_wan | REAL | Amount still outstanding |
| resolution_method | TEXT | Payment plan / lump sum / negotiation |
| resolution_month | TEXT | Expected resolution month |
| status | TEXT | 已化解/部分化解/未启动 |
| priority | TEXT | 高/中/低 |
```

## 第四步：生成看板

### 标准 Transformation KPI 看板

当你需要为 Sun Hing KPI 数据库生成完整的看板时，请按以下结构产出。

#### 顶部：6 个关键指标卡片（最新月份）

| 卡片 | 数据来源 | 格式 |
|---|---|---|
| 协商减员完成率 | fact_kpi_monthly WHERE kpi_id='01_协商减员完成率' | `{value}%` |
| 历史追缴化解率 | fact_kpi_monthly WHERE kpi_id='02_历史人力成本追缴化解率' | `{value}%` |
| 减员人数 | raw_hr latest | `{value}/{planned}` |
| 已支付成本(万) | raw_hr latest severance_paid_cumulative_wan | `{value}万` |
| 劳动纠纷 | raw_legal latest new_labor_arbitration_cases | `{value}` |
| ROE | fact_roe_summary latest | `{value}%` |

#### 中间：8 个标准图表

每个图表回答一个业务问题：

| # | 图表类型 | 业务问题 | 数据来源 |
|---|---|---|---|
| 1 | 柱状+折线图 | KPI #1 协商减员完成率月度趋势 vs target | fact_kpi_monthly (01), raw_hr |
| 2 | 柱状图 | KPI #2 追缴化解率月度进展 | fact_kpi_monthly (02), raw_finance |
| 3 | 折线图 | ROE 三因子趋势 (净利润率×资产周转率×权益乘数) | fact_roe_summary |
| 4 | 堆叠柱状图 | 总人数 + 生产人员占比变化 | raw_hr |
| 5 | 饼图 | 追缴项目分类 (社保/公积金/年金/税务/其他) | raw_liability |
| 6 | 散点图 | 核心厂区 vs 生态伙伴利润贡献趋势 | raw_finance |
| 7 | 柱状图 | 技术骨干留任率月度趋势 | fact_kpi_monthly (18) |
| 8 | 热力图 | 风险指标综合预警 (纠纷/满意度/舆情) | raw_legal + raw_sentiment |

#### 底部：业务洞察

给出 3-5 条关键结论，把数字翻译成业务语言。

#### 设计规范

- 语言：中文（指标名称、轴标签、标题）
- 色系：#1a1a2e (navy) + #2ca02c (green, for met target) + #e74c3c (red, for warning)
- 布局：最顶部 KPI 行，中间图表网格 2×4，底部洞察卡片
- 图表库：Plotly.js (CDN: https://cdn.plot.ly/plotly-2.35.2.min.js)
- 数据嵌入：Mode B — `var EMBEDDED_DATA = {...}` 直接嵌入 HTML，不用 fetch
