---
name: data-analysis
description: >-
  Content-independent data analysis mechanics. Provides chart types, tool usage patterns, and edge case handling for CSV and SQL data. Pair with a dataset-specific .skill.md for column semantics and business context.
tags: [data-analysis, csv, sql, pandas, matplotlib, visualization, analytics]
triggers:
  - "when user uploaded a CSV file"
  - "when user asks to analyze data"
  - "when user asks about database or SQL"
  - "when user wants data visualization or charts"
allowed-tools: [execute, filesystem, read_file, save_analysis_result]
author: LangConfig
---

# Data Analysis Skill (System)

Content-independent mechanics for **CSV files** and **SQL databases**.
Relies on the bundled Python script `scripts/data_analysis.py` for standard operations.

**Important**: The user may have uploaded a `.skill.md` companion file alongside
their data (or one was auto-generated from the CSV). That companion describes
column semantics, business logic, and common patterns for *this specific dataset*.
Treat the companion as authoritative for interpretation. Use this skill for the
*mechanics* of analysis — chart types, tool invocation, edge case handling.

## Data Source

### Accepted inputs
- **CSV files**: any tabular CSV with header row
- **SQL queries**: any `SELECT` statement against PostgreSQL (via `DATABASE_URL`)

### Bundled script
`scripts/data_analysis.py` — deterministic analyzer that runs profile + aggregate + chart in one pass.
Invoke it via `execute` with JSON on stdin.

## Invocation

Pass a JSON payload via stdin to the bundled script:

```bash
echo '{"source_type":"csv","file_path":"/path/to/data.csv"}' \
  | python /data-analysis/scripts/data_analysis.py
```

### Input fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `source_type` | yes | `csv` or `sql` | Determines loader |
| `file_path` | if csv | string | Absolute path to CSV |
| `query` | if sql | string | SQL SELECT statement |
| `group_by` | no | string | Column name for grouping |
| `agg_column` | no | string | Column to aggregate (must be numeric) |
| `agg_funcs` | no | list | Default: `["sum", "mean", "count"]` |
| `chart_type` | no | `histogram` / `bar` / `line` / `scatter` / `subplots` | Chart kind |
| `x_column` | if chart | string | X-axis column |
| `y_column` | if chart | string | Y-axis column |
| `output_path` | no | string | Where to save PNG (default `/tmp/chart.png`) |
| `top_n` | no | int | Default 10 |

### Output fields

| Field | Type | Notes |
|---|---|---|
| `status` | `ok` / `error` | Script result |
| `profile.shape` | `[rows, cols]` | Dataset dimensions |
| `profile.columns` | list | Column names |
| `profile.dtypes` | dict | Per-column dtype |
| `profile.missing` | dict | Per-column NaN count |
| `aggregations` | nested dict | Group-by aggregations |
| `correlations` | dict | Pearson correlations (numeric pairs) |
| `charts` | list | Paths to generated PNG files |

## Mechanics

### Recommended metrics (select as appropriate)

Depending on the dataset and user's question, generate from:

1. **Shape** — `(rows, columns)`
2. **Columns** — list with dtypes
3. **Missing values** — count per column
4. **Numeric summary** — min, max, mean, median, std for each numeric column
5. **Categorical summary** — top value + frequency per categorical column
6. **Top-N groups** — by `group_by` + `agg_funcs`
7. **Correlations** — Pearson between numeric columns
8. **Outliers** — rows where numeric column is > 3 std from mean
9. **Distribution** — histogram shape
10. **Sample rows** — first 5 + last 5 rows

### Workflow

1. **Identify source** — CSV if user uploaded a file, SQL if user mentioned tables/queries.
2. **Load + Profile** — Run with just `source_type` + `file_path` (or `query`).
3. **Aggregate** — Add `group_by` + `agg_column` for group aggregations and correlations.
4. **Visualize** — Add `chart_type` + `x_column` + `y_column` to generate a chart.
5. **Report** — Summarize top 3 findings and link to the chart.

### Top 3 findings format

1. **The single most striking pattern** — e.g. "X is 3x larger than Y"
2. **A surprising outlier or anomaly** — e.g. "5% of rows have NaN in column Z"
3. **A useful actionable insight** — e.g. "Customer segment A has 2x higher churn"

### Dependencies

Sandbox must have: `pandas`, `sqlalchemy`, `psycopg2-binary`, `matplotlib`.
PostgreSQL connection string available at `DATABASE_URL` env var.

## Few-shot Examples

### Example 1: Profile-only analysis

```bash
echo '{"source_type":"csv","file_path":"/path/to/data.csv"}' \
  | python /data-analysis/scripts/data_analysis.py
```

Returns: shape, columns, dtypes, missing counts, numeric summary.

### Example 2: Aggregate by category

```bash
echo '{
  "source_type":"csv",
  "file_path":"/path/to/data.csv",
  "group_by":"category_column",
  "agg_column":"numeric_column",
  "agg_funcs":["sum","mean","count"]
}' | python /data-analysis/scripts/data_analysis.py
```

Returns: aggregations by category.

### Example 3: Scatter plot

```bash
echo '{
  "source_type":"csv",
  "file_path":"/path/to/data.csv",
  "chart_type":"scatter",
  "x_column":"column_a",
  "y_column":"column_b"
}' | python /data-analysis/scripts/data_analysis.py
```

Returns: chart path in `charts[0]`.

## Edge Cases

### 1. Empty CSV
`profile.shape = [0, N]` — suggest user check the file.

### 2. All-NaN column
Auto-excluded from aggregations.

### 3. Categorical with >50 unique values
Top-N by frequency, group remainder as "Other".

### 4. SQL query fails
Check connection string, retry once, surface user-visible error.

### 5. Time series with non-datetime column
Detect datetime columns; cast to `pd.to_datetime()` automatically.

### 6. Missing chart columns
Validate `x_column` and `y_column` exist BEFORE running.

### 7. Incompatible source_type fields
`csv` requires `file_path`, `sql` requires `query`.

## Decision criteria (when to use data-analysis-llm instead)

- User asks for custom ML model
- User asks for statistical test (t-test, chi-square)
- User asks open-ended exploration ("what's interesting?")
