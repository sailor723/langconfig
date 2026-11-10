---
name: data-analysis-llm（数据分析·LLM 驱动）
lang: zh
translated: machine
source: backend/skills/en-originals/data-analysis-llm/SKILL.md
description: "灵活的数据分析：由智能体依据用户的问题现场写 Python 代码。当用户的分析请求是定制的、新颖的、不符合任何预定义模式时使用。较慢，但更灵活。"
tags: [data-analysis, csv, sql, python, flexible, custom-analysis]
triggers:
  - "用户提出定制或新颖的数据问题时"
  - "用户要求的分析不在 data-analysis 覆盖范围内时"
  - "用户想要定制的可视化时"
  - "用户想做探索性数据分析时"
  - "分析问题是开放式的时候"
allowed-tools: [execute, filesystem]
author: LangConfig
---

# 数据分析（LLM 驱动）技能

你是一名灵活的数据分析师。当用户提出定制的、新颖的或开放式的数据分析问题（也就是不符合 `data-analysis` 那套固定 schema 的问题）时，你依据问题现场写 Python 代码，然后用 `execute` 工具跑它。

## Data Source（数据源）

### 接受的输入
- **CSV 文件**：任何表格型 CSV（路径经 `UPLOADED_FILE` 环境变量传入，或由用户指定）
- **SQL 查询**：任何针对 PostgreSQL 的 `SELECT`（经 `DATABASE_URL`）
- **内存中的数据**：用户作为上下文提供的任何东西

### 运行时环境
- **沙箱**：经 `execute` 工具启动的临时 Python 进程
- **可用库**：pandas、numpy、sqlalchemy、psycopg2-binary、matplotlib、scipy
- **输出通道**：stdout（文本）与 `/uploads/charts/*.png`（可视化）

## Column Metadata（列元数据）

| 字段 | 必填 | 数据类型 | 语义 | 用法 |
|---|---|---|---|---|
| `source_type` | 是 | enum（`csv` / `sql` / `inline`） | 输入格式 | 决定用哪个加载器 |
| `source_path` | csv 时 | string（绝对路径） | CSV 位置 | 由 pandas 读取 |
| `query` | sql 时 | string（SQL SELECT） | 查询文本 | 经 SQLAlchemy 执行 |
| `intent` | 是 | string（自然语言） | 用户的分析问题 | 驱动代码生成 |
| `output_format` | 否 | enum（`text` / `json` / `chart`） | 结果格式 | 默认 `text` |

**注意**：与 `data-analysis` 不同，本技能对"要算什么"没有任何固定 schema。智能体从用户的意图出发生成代码。

## Business Logic（业务逻辑）

### 什么时候用本技能，什么时候用 `data-analysis`

| 用 `data-analysis`（确定性） | 用 `data-analysis-llm`（灵活，也就是本技能） |
|---|---|
| 标准的画像/聚合/画图 | 定制计算 |
| 预定义的输入 schema | 自由形式的用户问题 |
| 快、确定性、可预期 | 灵活、较慢、能处理新颖查询 |
| 每次跑出来答案一样 | 答案随模型而变 |

### 工作流

```
1. Understand the user's question
2. Identify the data source (CSV path or SQL query)
3. Write a focused Python script that answers the question
4. Use execute() to run it
5. Interpret the output and explain findings
```

### 约定

- 图表存到 `/uploads/charts/<name>.png`（或用户指定的路径）
- 结果以文本打印——`execute` 工具返回的就是 stdout
- 要 JSON 输出，用 `json.dumps(result)` 再经 stdout 取回
- 结果很大就写进文件，然后引用那个路径
- 无头生成图表时，永远带上 `matplotlib.use("Agg")`

### 输出格式（跑完之后）

按这个顺序呈现：
1. **你算了什么**（简要描述）
2. **关键结论**（从输出里读出的洞察）
3. **可视化**（如果生成了图表，就链接到它）
4. **建议**（下一步，或需要提醒的坑）

### 重试策略

- 代码失败 → 读错误，改，重试（最多 3 次）
- 3 次之后 → 把错误摊给用户，请他给方向

## Few-shot Examples（少样本示例）

### 示例 1：自定义相关性分析（价格与时间）

用户问：*"价格和日期之间有没有什么不寻常的相关性？"*

```python
import pandas as pd
import os

df = pd.read_csv(os.environ["UPLOADED_FILE"])

# Custom: rolling correlation between price and time
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date")
df["price_rolling"] = df["price"].rolling(7).mean()
df["price_lag7"] = df["price"].shift(7)
corr = df[["price", "price_lag7", "price_rolling"]].corr()
print(corr.to_string())
```

### 示例 2：自定义统计检验（这个分布是正态的吗？）

用户问：*"`fare` 列是正态分布吗？"*

```python
import pandas as pd
from scipy import stats
import os

df = pd.read_csv(os.environ["UPLOADED_FILE"])
stat, p_value = stats.shapiro(df["fare"].dropna())
print(f"Shapiro-Wilk test: statistic={stat:.4f}, p-value={p_value:.4e}")
if p_value < 0.05:
    print("Reject normality — distribution is NOT normal")
else:
    print("Cannot reject normality — distribution may be normal")
```

### 示例 3：自定义预测（线性回归）

用户问：*"用年龄和舱位预测票价"*

```python
import pandas as pd
from sklearn.linear_model import LinearRegression
import os

df = pd.read_csv(os.environ["UPLOADED_FILE"]).dropna(subset=["age", "fare", "pclass"])
X = df[["age", "pclass"]]
y = df["fare"]
model = LinearRegression().fit(X, y)
print(f"Coefficients: age={model.coef_[0]:.2f}, pclass={model.coef_[1]:.2f}")
print(f"R²: {model.score(X, y):.3f}")
```

## Edge Cases & Pitfalls（边界情况与坑）

### 1. 用户的问题有歧义
❌ 靠猜意图去写代码
✅ 写代码之前，先就数据源与意图问清楚

### 2. 代码反复失败
❌ 拿着同一份坏代码一直重试
✅ 3 次之后，把错误摊出来并请对方给方向

### 3. 结果出乎意料
❌ 就这么报出去
✅ 复核数据，先跑一遍 `data-analysis` 的画像，再重试

### 4. 图表显示不出来
❌ 忘了 `matplotlib.use("Agg")`——脚本会卡在显示上
✅ 无头渲染永远设 `Agg` 后端

### 5. 数据集太大，内存装不下
❌ 把整个 CSV 读进 pandas
✅ 用 `pd.read_csv(chunksize=10000)`，或在上游先过滤

### 6. 密钥泄漏
❌ 在脚本里硬编码 API key、数据库凭据
✅ 只用环境变量（`os.environ["DATABASE_URL"]` 等）

### 7. SQL 注入风险
❌ 把用户输入拼进查询字符串
✅ 用参数化查询：`text("SELECT * FROM x WHERE id = :id")`

### 8. 导入了不可用的库
❌ `import tensorflow as tf`——沙箱里多半没装
✅ 只用文档列明的这套库：pandas、numpy、sqlalchemy、psycopg2-binary、matplotlib、scipy

## Decision criteria（判定标准）

当用户的问题不符合 `data-analysis` 的固定模式时：
- 新颖的统计检验（例如"这个分布是正态的吗？"）
- 定制的 ML 模型（例如"从 Y 预测 X"）
- 复杂的多步分析
- 领域专用计算
- 任何需要解读的问题

→ 用**本技能**（写 Python，执行它）

当用户要的是标准的画像/聚合/画图时：
- "给我看摘要统计"
- "按类别分组求和"
- "画个柱状图"

→ 用 `data-analysis`（那个确定性技能）
