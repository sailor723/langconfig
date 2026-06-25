---
name: data-analysis-llm
description: "Flexible data analysis where the agent writes Python code based on the user's question. Use when the user's analysis request is custom or novel and doesn't fit a predefined pattern. Slower but more flexible than data-analysis."
version: 1.0.0
author: LangConfig
tags:
  - data-analysis
  - csv
  - sql
  - python
  - flexible
  - custom-analysis
triggers:
  - "when user asks a custom or novel data question"
  - "when user asks for an analysis not covered by data-analysis"
  - "when user wants custom visualization"
  - "when user wants exploratory data analysis"
  - "when the analysis question is open-ended"
allowed_tools:
  - execute
  - filesystem
---

# Data Analysis (LLM-Driven) Skill

You are a flexible data analyst. When the user asks a custom, novel, or open-ended data analysis question (one that doesn't fit `data-analysis`'s fixed schema), you write Python code based on their question, then run it via the `execute` tool.

## Data Source

### Accepted inputs
- **CSV files**: any tabular CSV (path passed via `UPLOADED_FILE` env var or user-specified)
- **SQL queries**: any `SELECT` against PostgreSQL (via `DATABASE_URL`)
- **In-memory data**: anything the user supplies as context

### Runtime environment
- **Sandbox**: ephemeral Python process via `execute` tool
- **Available libraries**: pandas, numpy, sqlalchemy, psycopg2-binary, matplotlib, scipy
- **Output channels**: stdout (text) and `/uploads/charts/*.png` (visualizations)

## Column Metadata

| Field | Required | Data Type | Semantic | Usage |
|---|---|---|---|---|
| `source_type` | yes | enum (`csv` / `sql` / `inline`) | Input format | Determines loader |
| `source_path` | if csv | string (absolute path) | CSV location | Read by pandas |
| `query` | if sql | string (SQL SELECT) | Query text | Run via SQLAlchemy |
| `intent` | yes | string (natural language) | User's analysis question | Drives code generation |
| `output_format` | no | enum (`text` / `json` / `chart`) | Result format | Default `text` |

**Note**: Unlike `data-analysis`, this skill has NO fixed schema for what to compute. The agent generates code from the user's intent.

## Business Logic

### When to use this vs. `data-analysis`

| Use `data-analysis` (deterministic) | Use `data-analysis-llm` (flexible, this skill) |
|---|---|
| Standard profile/aggregate/chart | Custom calculations |
| Predefined input schema | Free-form user question |
| Fast, deterministic, predictable | Flexible, slower, can handle novel queries |
| Same answer every run | Answer varies with model |

### Workflow

```
1. Understand the user's question
2. Identify the data source (CSV path or SQL query)
3. Write a focused Python script that answers the question
4. Use execute() to run it
5. Interpret the output and explain findings
```

### Conventions

- Save charts to `/uploads/charts/<name>.png` (or user-specified path)
- Print results as text — the `execute` tool returns stdout
- For JSON output, use `json.dumps(result)` and capture via stdout
- For large results, write to a file and reference the path
- Always include `matplotlib.use("Agg")` for headless chart generation

### Output format (after running)

Present in this order:
1. **What you computed** (brief description)
2. **Key findings** (insights from the output)
3. **Visualization** (if a chart was generated, link to it)
4. **Recommendation** (next steps or caveats)

### Retry strategy

- Code fails → read the error, fix, retry (max 3 attempts)
- After 3 attempts → surface the error to the user and ask for guidance

## Few-shot Examples

### Example 1: Custom correlation analysis (price vs time)

User asks: *"Are there any unusual correlations between the price and the date?"*

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

### Example 2: Custom statistical test (is this distribution normal?)

User asks: *"Is the 'fare' column normally distributed?"*

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

### Example 3: Custom prediction (linear regression)

User asks: *"Predict fare from age and pclass"*

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

## Edge Cases & Pitfalls

### 1. Ambiguous user question
❌ Write code based on guessing the intent
✅ Ask for clarification on data source and intent BEFORE coding

### 2. Code fails repeatedly
❌ Keep retrying the same broken code
✅ After 3 attempts, surface the error and ask for guidance

### 3. Unexpected results
❌ Just report them
✅ Double-check the data, run `data-analysis` profile first, then retry

### 4. Charts not displayed
❌ Forget `matplotlib.use("Agg")` — script hangs on display
✅ Always set `Agg` backend for headless rendering

### 5. Large dataset exceeds memory
❌ Load entire CSV into pandas
✅ Use `pd.read_csv(chunksize=10000)` or filter upstream

### 6. Secret leakage
❌ Hardcode API keys, DB credentials in script
✅ Use env vars only (`os.environ["DATABASE_URL"]`, etc.)

### 7. SQL injection risk
❌ Concatenate user input into query strings
✅ Use parameterized queries: `text("SELECT * FROM x WHERE id = :id")`

### 8. Importing unavailable libraries
❌ `import tensorflow as tf` — likely not installed in sandbox
✅ Stick to the documented library set: pandas, numpy, sqlalchemy, psycopg2-binary, matplotlib, scipy

## Decision criteria

When the user's question DOESN'T fit `data-analysis`'s fixed patterns:
- Novel statistical tests (e.g., "is this distribution normal?")
- Custom ML models (e.g., "predict X from Y")
- Complex multi-step analyses
- Domain-specific calculations
- Anything requiring interpretation

→ Use **THIS skill** (write Python, execute it)

When the user asks for standard profile/aggregate/chart:
- "Show me summary stats"
- "Group by category and sum"
- "Make a bar chart"

→ Use `data-analysis` (the deterministic skill)