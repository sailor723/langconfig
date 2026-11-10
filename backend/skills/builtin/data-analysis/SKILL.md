---
name: data-analysis（数据分析）
lang: zh
translated: machine
source: backend/skills/en-originals/data-analysis/SKILL.md
description: >-
  与具体内容无关的数据分析机制。提供图表类型、工具用法模式，以及 CSV 与 SQL 数据的边界情况处理。与某个
  数据集专用的 .skill.md 搭配使用，那个文件给出列语义与业务背景。
tags: [data-analysis, csv, sql, pandas, matplotlib, visualization, analytics]
triggers:
  - "用户上传了 CSV 文件时"
  - "用户要求分析数据时"
  - "用户问起数据库或 SQL 时"
  - "用户想要数据可视化或图表时"
allowed-tools: [execute, filesystem, read_file, save_analysis_result]
author: LangConfig
---

# 数据分析技能（系统）

面向 **CSV 文件**与 **SQL 数据库**、与具体内容无关的机制。
标准操作依赖随包附带的 Python 脚本 `scripts/data_analysis.py`。

**重要**：用户可能随数据一起上传了一份 `.skill.md` 伴生文件（也可能是从 CSV 自动生成的一份）。
那份伴生文件描述*这个具体数据集*的列语义、业务逻辑与常见模式。
解读数据时以伴生文件为准。本技能负责分析的*机制*——图表类型、工具调用方式、边界情况处理。

## Data Source（数据源）

### 接受的输入
- **CSV 文件**：任何带表头的表格型 CSV
- **SQL 查询**：任何针对 PostgreSQL 的 `SELECT` 语句（经 `DATABASE_URL`）

### 随包脚本
`scripts/data_analysis.py` —— 确定性分析器，一趟跑完 profile + aggregate + chart。
通过 `execute` 调用它，JSON 从 stdin 传入。

## Invocation（调用方式）

把一份 JSON 载荷经 stdin 传给随包脚本：

```bash
echo '{"source_type":"csv","file_path":"/path/to/data.csv"}' \
  | python /data-analysis/scripts/data_analysis.py
```

### 输入字段

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `source_type` | 是 | `csv` 或 `sql` | 决定用哪个加载器 |
| `file_path` | csv 时 | string | CSV 的绝对路径 |
| `query` | sql 时 | string | SQL SELECT 语句 |
| `group_by` | 否 | string | 用于分组的列名 |
| `agg_column` | 否 | string | 要聚合的列（必须是数值型） |
| `agg_funcs` | 否 | list | 默认 `["sum", "mean", "count"]` |
| `chart_type` | 否 | `histogram` / `bar` / `line` / `scatter` / `subplots` | 图表种类 |
| `x_column` | 画图时 | string | X 轴列 |
| `y_column` | 画图时 | string | Y 轴列 |
| `output_path` | 否 | string | PNG 存到哪里（默认 `/tmp/chart.png`） |
| `top_n` | 否 | int | 默认 10 |

### 输出字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `ok` / `error` | 脚本结果 |
| `profile.shape` | `[rows, cols]` | 数据集维度 |
| `profile.columns` | list | 列名 |
| `profile.dtypes` | dict | 每一列的 dtype |
| `profile.missing` | dict | 每一列的 NaN 计数 |
| `aggregations` | nested dict | 分组聚合结果 |
| `correlations` | dict | Pearson 相关系数（数值列两两之间） |
| `charts` | list | 生成的 PNG 文件路径 |

## Mechanics（分析机制）

### 建议计算的指标（按需选择）

视数据集与用户的问题而定，从下面这些里生成：

1. **形状** —— `(rows, columns)`
2. **列** —— 带 dtype 的列表
3. **缺失值** —— 每一列的计数
4. **数值摘要** —— 每个数值列的 min、max、mean、median、std
5. **类别摘要** —— 每个类别列的最高频取值 + 频次
6. **Top-N 分组** —— 按 `group_by` + `agg_funcs`
7. **相关性** —— 数值列之间的 Pearson 系数
8. **离群值** —— 数值列偏离均值超过 3 个标准差的那些行
9. **分布** —— 直方图形态
10. **样例行** —— 前 5 行 + 后 5 行

### 工作流

1. **确定数据源** —— 用户上传了文件就用 CSV；用户提到表或查询就用 SQL。
2. **加载 + 画像** —— 只带 `source_type` + `file_path`（或 `query`）跑一遍。
3. **聚合** —— 加上 `group_by` + `agg_column`，得到分组聚合与相关性。
4. **可视化** —— 加上 `chart_type` + `x_column` + `y_column` 生成图表。
5. **汇报** —— 总结最重要的 3 条结论，并链接到图表。

### 3 条结论的写法

1. **最突出的那一个模式** —— 例如"X 是 Y 的 3 倍"
2. **一个出人意料的离群值或异常** —— 例如"5% 的行在 Z 列上是 NaN"
3. **一条有用、可落地的洞察** —— 例如"客户细分 A 的流失率是其他细分的 2 倍"

### 依赖

沙箱里必须有：`pandas`、`sqlalchemy`、`psycopg2-binary`、`matplotlib`。
PostgreSQL 连接串从环境变量 `DATABASE_URL` 取。

## Few-shot Examples（少样本示例）

### 示例 1：只做画像分析

```bash
echo '{"source_type":"csv","file_path":"/path/to/data.csv"}' \
  | python /data-analysis/scripts/data_analysis.py
```

返回：shape、columns、dtypes、缺失计数、数值摘要。

### 示例 2：按类别聚合

```bash
echo '{
  "source_type":"csv",
  "file_path":"/path/to/data.csv",
  "group_by":"category_column",
  "agg_column":"numeric_column",
  "agg_funcs":["sum","mean","count"]
}' | python /data-analysis/scripts/data_analysis.py
```

返回：按类别聚合的结果。

### 示例 3：散点图

```bash
echo '{
  "source_type":"csv",
  "file_path":"/path/to/data.csv",
  "chart_type":"scatter",
  "x_column":"column_a",
  "y_column":"column_b"
}' | python /data-analysis/scripts/data_analysis.py
```

返回：图表路径在 `charts[0]`。

## Edge Cases（边界情况）

### 1. 空 CSV
`profile.shape = [0, N]` —— 建议用户检查文件。

### 2. 整列都是 NaN
自动从聚合里排除。

### 3. 类别列的不同取值超过 50 个
按频次取 Top-N，剩下的归并成 "Other"。

### 4. SQL 查询失败
检查连接串，重试一次，把错误以用户可见的方式报出来。

### 5. 时间序列的列不是 datetime 类型
识别 datetime 列，自动用 `pd.to_datetime()` 转换。

### 6. 画图缺列
跑之前先校验 `x_column` 与 `y_column` 确实存在。

### 7. source_type 与字段不匹配
`csv` 需要 `file_path`，`sql` 需要 `query`。

## Decision criteria (when to use data-analysis-llm instead)（判定标准：什么时候改用 data-analysis-llm）

- 用户要求定制一个 ML 模型
- 用户要求统计检验（t 检验、卡方检验）
- 用户要做开放式探索（"有什么有意思的？"）
