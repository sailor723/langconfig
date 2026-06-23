#!/usr/bin/env python3
"""
Data analysis skill — unified CSV/SQL profiling, aggregation, and visualization.

Pattern: matches LangChain deepagents' arxiv-search example
  - SKILL.md describes when to use this
  - data_analysis.py is the single implementation
  - JSON stdin → JSON stdout contract

Usage (called by agent via the execute tool):
    echo '{"source_type":"csv","file_path":"data.csv","group_by":"category","agg_column":"value"}' \\
        | python data_analysis.py

Dependencies: pandas, sqlalchemy, psycopg2-binary, matplotlib
"""

import sys
import json
import os


def load_dataframe(payload):
    """Load DataFrame from CSV path or SQL query."""
    import pandas as pd

    source_type = payload.get("source_type", "csv")

    if source_type == "csv":
        file_path = payload.get("file_path")
        if not file_path or not os.path.exists(file_path):
            raise ValueError(f"CSV file not found: {file_path}")
        return pd.read_csv(file_path), f"csv:{file_path}"

    if source_type == "sql":
        query = payload.get("query")
        if not query:
            raise ValueError("SQL source requires 'query' field")
        conn_str = payload.get("connection_string") or os.environ.get(
            "DATABASE_URL",
            "postgresql://langconfig:langconfig_dev@localhost:5433/langconfig",
        )
        from sqlalchemy import create_engine
        engine = create_engine(conn_str)
        df = pd.read_sql(query, engine)
        return df, f"sql:{query[:60]}..."

    raise ValueError(f"Unknown source_type: {source_type}")


def profile(df):
    """Compute shape, missing values, dtypes, describe, top values."""
    import pandas as pd

    profile = {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing": {col: int(df[col].isnull().sum()) for col in df.columns},
        "missing_pct": {
            col: round(int(df[col].isnull().sum()) / max(int(df.shape[0]), 1) * 100, 2)
            for col in df.columns
        },
        "sample": df.head(5).to_dict(orient="records"),
    }

    # describe (numeric + categorical)
    try:
        desc = df.describe(include="all").fillna("")
        profile["describe"] = {
            col: {k: _to_native(v) for k, v in desc[col].items()}
            for col in desc.columns
        }
    except Exception:
        pass

    # top values for object/category columns
    for col in df.columns:
        if df[col].dtype == "object" or str(df[col].dtype) == "category":
            top = df[col].value_counts().head(5).to_dict()
            profile.setdefault("top_values", {})[col] = {str(k): int(v) for k, v in top.items()}

    return profile


def aggregate(df, payload):
    """Group-by aggregations and correlations."""
    import pandas as pd

    result = {}
    group_by = payload.get("group_by")
    agg_column = payload.get("agg_column")
    agg_funcs = payload.get("agg_funcs", ["sum", "mean", "count"])
    top_n = payload.get("top_n", 10)

    # Group aggregations
    if group_by and agg_column and group_by in df.columns and agg_column in df.columns:
        agg_dict = {agg_column: agg_funcs}
        grouped = df.groupby(group_by).agg(agg_dict).round(2)
        grouped.columns = ["_".join(c).strip("_") for c in grouped.columns]
        grouped = grouped.reset_index()
        sort_col = f"{agg_column}_{agg_funcs[0]}" if agg_funcs else None
        if sort_col and sort_col in grouped.columns:
            grouped = grouped.sort_values(sort_col, ascending=False)
        result["groups"] = grouped.head(top_n).to_dict(orient="records")

    # Correlations
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] >= 2:
        result["correlations"] = numeric.corr().round(3).to_dict()

    return result


def visualize(df, payload):
    """Generate a matplotlib chart if requested."""
    chart_type = payload.get("chart_type")
    if not chart_type:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_path = payload.get("output_path", "/tmp/analysis_chart.png")
    x_col = payload.get("x_column")
    y_col = payload.get("y_column")
    group_col = payload.get("group_column")
    title = payload.get("title", f"{y_col or x_col} analysis")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5)) if chart_type == "subplots" else (None, None)

    if chart_type == "subplots" and y_col:
        # Distribution
        axes[0].hist(df[y_col].dropna(), bins=30, edgecolor="black", color="steelblue")
        axes[0].set_xlabel(y_col)
        axes[0].set_ylabel("Frequency")
        axes[0].set_title(f"Distribution of {y_col}")
        # Group means
        if group_col and group_col in df.columns:
            agg = df.groupby(group_col)[y_col].mean().sort_values(ascending=False).head(10)
            agg.plot(kind="bar", ax=axes[1], color="coral")
            axes[1].set_xlabel(group_col)
            axes[1].set_ylabel(f"Mean {y_col}")
            axes[1].set_title(f"Mean {y_col} by {group_col}")
    else:
        ax = plt.gca()
        if chart_type == "histogram" and x_col and x_col in df.columns:
            ax.hist(df[x_col].dropna(), bins=30, edgecolor="black")
            ax.set_xlabel(x_col)
            ax.set_ylabel("Frequency")
        elif chart_type == "bar" and x_col and y_col:
            df.groupby(x_col)[y_col].sum().sort_values(ascending=False).head(20).plot(kind="bar", ax=ax)
        elif chart_type == "line" and x_col and y_col:
            ax.plot(df[x_col], df[y_col])
        elif chart_type == "scatter" and x_col and y_col:
            ax.scatter(df[x_col], df[y_col], alpha=0.5)
        else:
            return None

    if hasattr(plt, "suptitle"):
        plt.suptitle(title)
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()

    return {
        "chart_path": output_path,
        "chart_type": chart_type,
        "file_size_bytes": os.path.getsize(output_path),
    }


def _to_native(v):
    """Convert numpy types to native Python for JSON serialization."""
    import numpy as np
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        if np.isnan(v):
            return None
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def main():
    try:
        payload = json.loads(sys.stdin.read())

        # 1. Load
        df, source = load_dataframe(payload)

        # 2. Profile (always)
        result = {"status": "ok", "source": source, "profile": profile(df)}

        # 3. Aggregate (if requested)
        if payload.get("group_by") or payload.get("agg_column"):
            result["aggregate"] = aggregate(df, payload)

        # 4. Visualize (if requested)
        chart = visualize(df, payload)
        if chart:
            result["chart"] = chart

        print(json.dumps(result, indent=2, default=_to_native))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()