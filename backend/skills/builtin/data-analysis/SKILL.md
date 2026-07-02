---
name: data-analysis
description: >-
  Analyze CSV files and SQL databases. Returns data profile, aggregations, correlations, and charts. Use when user wants to analyze data, query PostgreSQL, or generate visualizations.
tags: [data-analysis, csv, sql, postgresql, pandas, matplotlib, visualization, analytics]
triggers:
  - "when user uploads a CSV file"
  - "when user asks to analyze data"
  - "when user asks about database or SQL"
  - "when user wants to query the database"
  - "when user mentions PostgreSQL"
  - "when user wants data visualization or charts"
allowed-tools: [execute, filesystem]
author: LangConfig
---

# Data Analysis Skill

Analyze data from **CSV files** or **SQL databases** using the bundled Python script `scripts/data_analysis.py`.

## Data Source

### Accepted inputs
- **CSV files**: any tabular CSV with header row (e.g., Titanic, Iris, sales exports)
- **SQL queries**: any `SELECT` statement against PostgreSQL (via `DATABASE_URL`)

### Bundled script
`scripts/data_analysis.py` — deterministic analyzer that runs profile + aggregate + chart in one pass.

Sample invocation:
```bash
echo '{"source_type":"csv","file_path":"/uploads/titanic.csv"}' \
  | python /data-analysis/scripts/data_analysis.py
```

## Column Metadata

### Input schema (JSON via stdin)

| Field | Required | Data Type | Semantic | Usage |
|---|---|---|---|---|
| `source_type` | yes | enum (`csv` / `sql`) | Input format | Determines loader branch |
| `file_path` | if csv | string (absolute path) | CSV location | Read by pandas |
| `query` | if sql | string (SQL SELECT) | Query text | Run via SQLAlchemy |
| `group_by` | no | string (column name) | Column for grouping | Triggers aggregation step |
| `agg_column` | no | string (column name) | Column to aggregate | Must be numeric |
| `agg_funcs` | no | list of enums | Aggregation functions | Default `["sum", "mean", "count"]` |
| `chart_type` | no | enum (`histogram`/`bar`/`line`/`scatter`/`subplots`) | Chart kind | Triggers matplotlib render |
| `x_column` | if chart | string | X-axis column | Required for chart |
| `y_column` | if chart | string | Y-axis column | Required for chart |
| `output_path` | no | string (absolute path) | Where to save PNG | Default `/tmp/chart.png` |
| `top_n` | no | int | How many top groups | Default 10 |

### Output schema (JSON via stdout)

| Field | Type | Semantic |
|---|---|---|
| `status` | enum (`ok` / `error`) | Script result |
| `source` | string | Identifies what was analyzed |
| `profile.shape` | `[int, int]` | `[rows, columns]` |
| `profile.columns` | list of strings | Column names |
| `profile.dtypes` | dict | Per-column dtype |
| `profile.missing` | dict | Per-column NaN count |
| `aggregations` | nested dict | Group-by aggregations |
| `correlations` | dict | Pearson correlations (numeric pairs) |
| `charts` | list of strings | Paths to generated PNG files |

## Business Logic

### The 10 key metrics (always generate)

For every dataset, generate these 10 metrics:

1. **Shape** — `(rows, columns)`
2. **Columns** — list with dtypes
3. **Missing values** — count per column
4. **Numeric summary** — min, max, mean, median, std for each numeric column
5. **Categorical summary** — top value + frequency per categorical column
6. **Top-N groups** — by `group_by` + `agg_funcs`
7. **Correlations** — Pearson between numeric columns
8. **Outliers** — rows where numeric column is > 3 std from mean
9. **Distribution** — histogram shape (skew, kurtosis if scipy available)
10. **Sample rows** — first 5 + last 5 rows

### Decision tree (when to use this vs. data-analysis-llm)

```
Is the user's request standard?
  YES (profile, aggregate, chart)  → use data-analysis (this skill, deterministic)
  NO  (custom, novel, exploratory)  → use data-analysis-llm (flexible Python)
```

### Workflow

1. **Identify source** — CSV if user uploaded a file, SQL if user mentioned tables/queries.
2. **Load + Profile** — Run with just `source_type` + `file_path` (or `query`) — get the data profile.
3. **Aggregate** — Add `group_by` + `agg_column` to get group aggregations and correlations.
4. **Visualize** — Add `chart_type` + `x_column` + `y_column` to generate a chart.
5. **Report** — Summarize top 3 findings and link to the chart.

### Top 3 findings — what to highlight

Always end your analysis with the top 3 findings:

1. **The single most striking pattern** — e.g., "X is 3x larger than Y"
2. **A surprising outlier or anomaly** — e.g., "5% of rows have NaN in column Z"
3. **A useful actionable insight** — e.g., "Customer segment A has 2x higher churn"

### Dependencies

Sandbox must have: `pandas`, `sqlalchemy`, `psycopg2-binary`, `matplotlib`.
PostgreSQL connection string available at `DATABASE_URL` env var.

## Few-shot Examples

### Example 1: Titanic dataset analysis (profile only)

User asks: "Analyze the Titanic CSV I uploaded"

```bash
echo '{"source_type":"csv","file_path":"/uploads/titanic.csv"}' \
  | python /data-analysis/scripts/data_analysis.py
```

Returns profile: shape, columns, dtypes, missing counts, numeric summary, etc.

### Example 2: Aggregate revenue by region

User asks: "Show me total revenue by region"

```bash
echo '{
  "source_type":"sql",
  "query":"SELECT sales_region, total_amount FROM orders WHERE status='\''completed'\''",
  "group_by":"sales_region",
  "agg_column":"total_amount",
  "agg_funcs":["sum","mean","count"]
}' | python /data-analysis/scripts/data_analysis.py
```

Returns aggregations: by sales_region → {sum, mean, count}.

### Example 3: Scatter plot of age vs fare

User asks: "Plot age vs fare"

```bash
echo '{
  "source_type":"csv",
  "file_path":"/uploads/titanic.csv",
  "chart_type":"scatter",
  "x_column":"Age",
  "y_column":"Fare"
}' | python /data-analysis/scripts/data_analysis.py
```

Returns chart path in `charts[0]`.

## Edge Cases & Pitfalls

### 1. Empty CSV
❌ Crashes or returns unclear profile
✅ `profile.shape = [0, N]` — suggests user check the file

### 2. All-NaN column
❌ Including in aggregations pollutes sums
✅ Detected via `missing = 100%`, excluded automatically

### 3. Categorical with >50 unique values
❌ Group-by blows up output
✅ Top-N by frequency, group remainder as "Other"

### 4. SQL query fails
❌ Silent failure or unclear error
✅ Check connection string, retry once, surface user-visible error

### 5. Time series data as non-datetime x_column
❌ Line chart shows points in wrong order
✅ Detect datetime columns; cast to `pd.to_datetime()` automatically

### 6. Missing required chart columns
❌ Script errors with confusing message
✅ Validate `x_column` and `y_column` exist BEFORE running; pre-flight check

### 7. Mixing incompatible source_type fields
❌ `source_type=csv` with `query=...` — script silently uses one
✅ Validate: csv requires `file_path`, sql requires `query`

### 8. Database connection lost mid-query
❌ Partial results, hard to debug
✅ Wrap query in try/except, set short timeout, surface clear error

## Decision criteria (when NOT to use this skill)

- User asks for custom ML model → use `data-analysis-llm`
- User asks for statistical test (t-test, chi-square) → use `data-analysis-llm`
- User asks open-ended exploration ("what's interesting in this data?") → use `data-analysis-llm`