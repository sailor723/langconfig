---
name: data-analysis
description: Analyze CSV files and SQL databases. Returns data profile, aggregations, correlations, and charts. Use when user wants to analyze data, query PostgreSQL, or generate visualizations.
version: 3.0.0
author: LangConfig
tags:
  - data-analysis
  - csv
  - sql
  - postgresql
  - pandas
  - matplotlib
  - visualization
  - analytics
triggers:
  - when user uploads a CSV file
  - when user asks to analyze data
  - when user asks about database or SQL
  - when user wants to query the database
  - when user mentions PostgreSQL
  - when user wants data visualization or charts
allowed_tools:
  - execute
  - filesystem
---

# Data Analysis Skill

Analyze data from **CSV files** or **SQL databases** using the bundled Python script `scripts/data_analysis.py`.

## Instructions

You are a unified data analysis agent. The user wants insights from their data. Your job is to:

1. Read the CSV to understand columns and data
2. Generate a 10-key metrics overview
3. Identify top 3 findings
4. Provide detailed analysis with charts
5. Save results (chart images + summary JSON)

Always think through the steps in order, then call `execute()` to run the bundled script `scripts/data_analysis.py`.

### Step-by-step thinking pattern

Always approach data analysis this way. Show your thinking before each tool call:

```
<think>The user wants me to analyze the Titanic CSV data. Let me start by examining
the file and then performing a comprehensive analysis. I need to:
- Read the CSV to understand columns and data
- Generate 10 key metrics overview
- Identify top 3 findings
- Provide detailed analysis with charts
- Save results
</think>

I'll analyze the Titanic dataset comprehensively. Let me start by examining
the file structure.

<think>Let me explore the outputs directory and check the existing analysis files
to understand what's already been done.
</think>
```

### Workflow

1. **Identify source** — CSV if user uploaded a file, SQL if user mentioned tables/queries.
2. **Load + Profile** — Run with just `source_type` + `file_path` (or `query`) — get the data profile.
3. **Aggregate** — Add `group_by` + `agg_column` to get group aggregations and correlations.
4. **Visualize** — Add `chart_type` + `x_column` + `y_column` to generate a chart.
5. **Report** — Summarize top 3 findings and link to the chart.

### Decision tree

```
Is the user's request standard?
  YES (profile, aggregate, chart)  → use data-analysis (this skill, deterministic)
  NO  (custom, novel, exploratory)  → use data-analysis-llm (flexible Python)
```

### How to invoke the script

Run the bundled script from your skills directory:

```bash
python /data-analysis/scripts/data_analysis.py < input.json > output.json
```

Or via the execute tool:

```
execute(
    command="python /data-analysis/scripts/data_analysis.py",
    input_json={...}
)
```

### Input schema (JSON via stdin)

```json
{
  "source_type": "csv",
  "file_path": "/uploads/data.csv",
  "group_by": "category",
  "agg_column": "value",
  "agg_funcs": ["sum", "mean", "count"],
  "top_n": 10,
  "chart_type": "subplots",
  "x_column": "id",
  "y_column": "value",
  "group_column": "category",
  "output_path": "/uploads/chart.png",
  "title": "My Analysis"
}
```

| Field | Required | Description |
|---|---|---|
| `source_type` | yes | `"csv"` or `"sql"` |
| `file_path` | if csv | Path to CSV file |
| `query` | if sql | SQL SELECT statement |
| `group_by` | no | Column to group by for aggregation |
| `agg_column` | no | Column to aggregate |
| `agg_funcs` | no | List of funcs (default `["sum", "mean", "count"]`) |
| `chart_type` | no | `histogram`, `bar`, `line`, `scatter`, `subplots` |
| `x_column`, `y_column` | if chart | Columns for the chart |
| `output_path` | no | Where to save the chart PNG |
| `top_n` | no | How many top rows/groups to show |

### Output schema (JSON via stdout)

```json
{
  "status": "ok",
  "source": "csv:/uploads/data.csv",
  "profile": {
    "shape": [1000, 8],
    "columns": ["id", "name", "value", "category"],
    "dtypes": {"id": "int64", "name": "str"},
    "missing": {"id": 0, "name": 5}
  },
  "aggregations": {
    "by_category": {"sum": {...}, "mean": {...}}
  },
  "correlations": {"value_x_id": 0.85},
  "charts": ["/uploads/chart.png"]
}
```

### The 10 key metrics to always generate

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

### Top 3 findings — what to highlight

Always end your analysis with the top 3 findings:

1. **The single most striking pattern** — e.g., "X is 3x larger than Y"
2. **A surprising outlier or anomaly** — e.g., "5% of rows have NaN in column Z"
3. **A useful actionable insight** — e.g., "Customer segment A has 2x higher churn"

### Edge cases

- **Empty CSV**: Profile shows `shape: [0, N]`. Suggest the user check the file.
- **All-NaN column**: `missing` shows 100%. Exclude from aggregations automatically.
- **Time series data**: Use `chart_type: "line"` with datetime `x_column`.
- **Categorical with >50 unique values**: Top-N by frequency, group others as "Other".
- **SQL query fails**: Check connection string, retry once, fall back to user-visible error.

### Dependencies

Sandbox must have: `pandas`, `sqlalchemy`, `psycopg2-binary`, `matplotlib`.

PostgreSQL connection string available at `DATABASE_URL` env var.

## Examples

### Example 1: Titanic dataset analysis

User asks: "Analyze the Titanic CSV I uploaded"

Your thinking:

```
<think>The user uploaded a CSV. Let me read it first to understand columns.
The bundled script data_analysis.py will handle profile/aggregate/chart in one pass.
Let me run it with just source_type=csv + file_path to get the profile first.</think>
```

Your tool call:

```
execute(
    command="python /data-analysis/scripts/data_analysis.py",
    input_json={
        "source_type": "csv",
        "file_path": "/uploads/titanic.csv"
    }
)
```

Then read the output, identify top 3 findings, generate a chart, report.

## Decision criteria (when NOT to use this skill)

- User asks for custom ML model → use `data-analysis-llm`
- User asks for statistical test → use `data-analysis-llm`
- User asks open-ended exploration → use `data-analysis-llm`
- User asks "is this distribution normal?" → use `data-analysis-llm`