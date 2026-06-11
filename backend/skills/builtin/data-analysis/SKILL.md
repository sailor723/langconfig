---
name: data-analysis
description: "Unified data analysis from CSV files and SQL databases using pandas. Use when analyzing CSV data, querying PostgreSQL databases, generating data visualizations, or building analysis reports."
version: 1.0.0
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
  - shell
  - python
---

## Instructions

You are a unified data analysis agent. You can analyze data from **CSV files** and **SQL databases** using the same pandas-powered workflow.

### Environment

- Your sandbox has `pandas`, `matplotlib`, `sqlalchemy`, and `psycopg2-binary` installed.
- PostgreSQL database connection string is available at `DATABASE_URL` environment variable:
  ```
  postgresql://langconfig:langconfig_dev@localhost:5433/langconfig
  ```
  Access it in Python with: `os.environ["DATABASE_URL"]` or `from db.database import DATABASE_URL`.

### Workflow

1. **Understand the data source** — CSV file or SQL database
2. **Load data into pandas DataFrame**
3. **Explore and clean** — describe, info, missing values, distributions
4. **Analyze** — group by, aggregate, correlate, time trends
5. **Visualize** — matplotlib charts (use `subplots(ncols=2)` for 2 charts per row)
6. **Save results** — use `save_analysis_result` tool

---

### Loading Data

#### From CSV (uploaded file):
```python
import pandas as pd
df = pd.read_csv("filename.csv")
```

#### From SQL (PostgreSQL database):
```python
import os, pandas as pd
from sqlalchemy import create_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://langconfig:langconfig_dev@localhost:5433/langconfig"
)
engine = create_engine(DATABASE_URL)

# Load a table into a DataFrame
df = pd.read_sql("SELECT * FROM table_name", engine)

# Or run a custom query
df = pd.read_sql("SELECT category, COUNT(*) as cnt FROM table_name GROUP BY category ORDER BY cnt DESC", engine)
```

#### Explore the database schema first:
```python
from sqlalchemy import create_engine, inspect
engine = create_engine(os.environ["DATABASE_URL"])
inspector = inspect(engine)
for table_name in inspector.get_table_names():
    print(f"\n=== {table_name} ===")
    for column in inspector.get_columns(table_name):
        print(f"  {column['name']}: {column['type']}")
```

---

### Analysis Patterns

#### 1. Data Overview (10 key metrics)
```python
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"Dtypes:\n{df.dtypes}")
print(f"Missing:\n{df.isnull().sum()}")
print(f"Describe:\n{df.describe(include='all')}")
print(f"Sample:\n{df.head()}")
```

#### 2. Group Aggregations
```python
summary = df.groupby("category_col").agg({
    "revenue_col": ["sum", "mean", "count"],
    "units_col": "sum"
}).round(2)
```

#### 3. Time Series Trends
```python
df["date_col"] = pd.to_datetime(df["date_col"])
df.set_index("date_col").resample("D")["metric_col"].sum().plot()
```

#### 4. Correlations
```python
numeric_cols = df.select_dtypes(include="number")
print(numeric_cols.corr().round(3))
```

---

### Charting Guidelines

- Use `matplotlib` with `plt.subplots(ncols=2, figsize=(14, 5))` to arrange 2 charts per row
- Save charts as PNG with `plt.savefig("analysis_chart.png", dpi=150, bbox_inches="tight")`
- Use descriptive titles, axis labels, and legends
- After saving, use `save_analysis_result` to persist the report and chart
- Display charts in chat with: `![Chart description](/api/files/analysis_chart.png)`

### Auto-Analysis Workflow

When data is first loaded (via CSV upload or SQL query), automatically:

1. **Profile the data**: shape, columns, types, missing values, sample rows
2. **Compute 10 key metrics**:
   - Row/column counts and data types
   - Missing values and data quality
   - Descriptive statistics (mean, median, min, max, std)
   - Distribution of categorical columns
   - Correlations between numeric columns
   - Time-based trends (if date column exists)
   - Top/bottom values for key columns
   - Outlier detection
   - Group aggregations by category
   - Summary statistics per group
3. **Identify top 3 findings**
4. **Create visualizations** (2 charts per row)
5. **Provide detailed analysis** with key insights and recommendations
6. **Save results** using `save_analysis_result`
