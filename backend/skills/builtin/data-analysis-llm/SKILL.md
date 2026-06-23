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

Use this skill when the user's analysis request is **custom, novel, or open-ended** —
anything that doesn't fit the fixed patterns of `data-analysis`.

## When to use which

| Use `data-analysis` (this one) | Use `data-analysis-llm` |
|---|---|
| Standard profile/aggregate/chart | Custom calculations |
| Predefined input schema | Free-form user question |
| Fast, deterministic, predictable | Flexible, slower, can handle novel queries |
| Same answer every run | Answer varies with model |

## How this skill works

You (the agent) write Python code based on the user's question, then run it via the `execute` tool.

## Pattern

```
1. Understand the user's question
2. Identify the data source (CSV path or SQL query)
3. Write a focused Python script that answers the question
4. Use execute() to run it
5. Interpret the output and explain findings
```

## Example: Custom correlation analysis

User asks: *"Are there any unusual correlations between the price and the date?"*

The code you (the agent) should write and run:

```
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

Then `execute(command="python -c '<above code>'")`.

## Available libraries

The sandbox has these installed:
- `pandas` — DataFrame operations
- `numpy` — numerical
- `sqlalchemy`, `psycopg2-binary` — SQL
- `matplotlib` — charts (`matplotlib.use("Agg")` for headless)
- `scipy` — statistics

## Conventions

- Save charts to `/uploads/charts/<name>.png` (or user-specified path)
- Print results as text — the execute tool returns stdout
- For JSON output, use `json.dumps(result)` and capture via stdout
- For large results, write to a file and reference the path

## Decision criteria

When the user asks something that DOESN'T fit the fixed `data-analysis` patterns:
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

## Output format

After running, present:
1. **What you computed** (brief description)
2. **Key findings** (insights from the output)
3. **Visualization** (if you generated a chart, link to it)
4. **Recommendation** (next steps or caveats)

## Edge cases

- User's question is ambiguous → ask for clarification on data source and intent
- Code fails → read the error, fix, retry (max 3 attempts)
- Result is unexpected → double-check the data, profile first, then retry
- Time-consuming analysis → warn user, use sampling if needed