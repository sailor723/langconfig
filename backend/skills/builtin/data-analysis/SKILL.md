---
name: Data Analysis
...
description: smoke test description 2
...
version: 3.0.0
...
author: LangConfig
...
tags: - data-analysis
- csv
- sql
- postgresql
- pandas
- matplotlib
- visualization
- analytics
triggers: - when user uploads a CSV file
- when user asks to analyze data
- when user asks about database or SQL
- when user wants to query the database
- when user mentions PostgreSQL
- when user wants data visualization or charts
allowed_tools: - filesystem
- shell
---

Use this skill when the user asks to analyze data from CSV files or SQL databases,
or wants data visualizations, aggregations, or correlations. The bundled script
`data_analysis.py` handles profile, aggregation, and chart generation.

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
