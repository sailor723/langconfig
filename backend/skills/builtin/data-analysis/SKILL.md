---
name: data-analysis
description: "Analyze CSV files and SQL databases. Returns data profile, aggregations, correlations, and charts. Use when user wants to analyze data, query PostgreSQL, or generate visualizations."
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
  - "when user uploads a CSV file"
  - "when user asks to analyze data"
  - "when user asks about database or SQL"
  - "when user wants to query the database"
  - "when user mentions PostgreSQL"
  - "when user wants data visualization or charts"
allowed_tools:
  - execute
  - filesystem
---

# Data Analysis Skill

Analyze data from **CSV files** or **SQL databases**. Run `data_analysis.py` via the `execute` tool.

## Usage

Run the bundled script from your skills directory:

```bash
python /data-analysis/data_analysis.py < input.json > output.json
```

Or via the execute tool:

```
execute(
    command="python /data-analysis/data_analysis.py",
    input_json={...}
)
```

## Input schema (JSON via stdin)

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
| `agg_funcs` | no | List of funcs (default: `["sum", "mean", "count"]`) |
| `chart_type` | no | `histogram`, `bar`, `line`, `scatter`, `subplots` |
| `x_column`, `y_column` | if chart | Columns for the chart |
| `output_path` | no | Where to save the chart PNG |

## Output schema (JSON via stdout)

```json
{
  "status": "ok",
  "source": "csv:/uploads/data.csv",
  "profile": {
    "shape": [1000, 8],
    "columns": ["id", "name", "value", "category"],
    "dtypes": {"id": "int64", "name": "str", "value": "int64"},
    "missing": {"id": 0, "name": 5},
    "sample": [...]
  },
  "aggregate": {
    "groups": [{"category": "A", "value_sum": 5000, "value_mean": 250.0}],
    "correlations": {"id": {"value": 0.95}}
  },
  "chart": {
    "chart_path": "/uploads/chart.png",
    "chart_type": "subplots",
    "file_size_bytes": 45678
  }
}
```

## Workflow

1. **Identify source**: CSV if user uploaded a file, SQL if user mentioned tables/queries.
2. **Load + Profile**: Run with just `source_type` + `file_path` (or `query`) — get the data profile.
3. **Aggregate**: Add `group_by` + `agg_column` to get group aggregations and correlations.
4. **Visualize**: Add `chart_type` + `x_column` + `y_column` to generate a chart.
5. **Report**: Summarize top 3 findings and link to the chart.

## Dependencies

Sandbox must have: `pandas`, `sqlalchemy`, `psycopg2-binary`, `matplotlib`.

PostgreSQL connection string available at `DATABASE_URL` env var.