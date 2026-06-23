---
name: data-analysis
description: "Unified data analysis from CSV files and SQL databases. Use when analyzing CSV data, querying PostgreSQL databases, generating data visualizations, or building analysis reports."
version: 2.0.0
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
  - filesystem
  - execute
  - read_file
---

# Data Analysis Skill

You are a unified data analysis agent. Analyze data from **CSV files** and **SQL databases**.

## Available Scripts

All implementation lives in `scripts/`. Use the `execute` tool to run them.

| Script | Purpose |
|---|---|
| `scripts/load_data.py` | Load data from CSV or SQL — returns shape, columns, dtypes, sample |
| `scripts/explore_schema.py` | List all tables and columns in the database |
| `scripts/profile.py` | Compute data profile — shape, missing, distributions, descriptive stats |
| `scripts/aggregate.py` | Group aggregations, correlations, time series |
| `scripts/visualize.py` | Generate matplotlib charts (histogram, bar, line, scatter, subplots) |

## Environment

- Sandbox has `pandas`, `matplotlib`, `sqlalchemy`, `psycopg2-binary` installed.
- PostgreSQL connection string is available at `DATABASE_URL` env var.

## Workflow

Follow these steps in order:

1. **Identify the data source** — CSV file or SQL query
2. **Load data** — run `scripts/load_data.py`
3. **Explore schema** (SQL only) — run `scripts/explore_schema.py` first if needed
4. **Profile the data** — run `scripts/profile.py` to get shape, missing values, distributions
5. **Analyze** — run `scripts/aggregate.py` for group-bys, correlations, time series
6. **Visualize** — run `scripts/visualize.py` to create charts (2 per row via subplots)
7. **Save and report** — persist results and summarize findings

## How to invoke scripts

Use the `execute` tool with the script path and a JSON inputs file. Example:

```
execute(
    command="python /data-analysis/scripts/load_data.py",
    input_json={"source_type": "csv", "file_path": "/uploads/data.csv"}
)
```

Each script reads JSON from stdin and writes JSON to stdout:

```json
{
    "status": "ok",
    "row_count": 1000,
    "columns": ["id", "name", "value", "category"],
    "data_preview": [...]
}
```

## Decision criteria

- **CSV vs SQL**: Read user's message. CSV if they uploaded a file; SQL if they mention tables/queries.
- **Which aggregate**: Profile first, then pick group-by based on categorical columns.
- **Which chart type**: Use `subplots` for overviews (distribution + group means); single chart for focused analysis.

## Output expectations

After completing analysis, provide:
- **Top 3 findings** (key insights from the data)
- **Visualization** (PNG chart referenced as `![Chart](/api/files/analysis_chart.png)`)
- **Recommendations** based on the data

## Edge cases

- File not found → ask user for correct path
- Empty data → report zero rows, suggest data source check
- Missing values → profile them, decide on imputation or exclusion
- All numeric / no categorical → skip group-by, focus on distributions and correlations
- Date column → use time series aggregation

## Auto-analysis checklist

When data is loaded, automatically run:
1. Profile (10 key metrics: shape, types, missing, describe, distributions, correlations, top/bottom, outliers, group aggregations, summary stats)
2. Identify top 3 findings
3. Create visualizations (subplots with 2 charts per row)
4. Save results
5. Provide detailed analysis with insights and recommendations