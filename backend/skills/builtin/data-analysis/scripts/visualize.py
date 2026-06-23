#!/usr/bin/env python3
"""
Generate matplotlib charts from a data file.

Inputs (from stdin JSON):
    {
        "data_path": "path/to/data.csv",
        "chart_type": "histogram" | "bar" | "line" | "scatter" | "subplots",
        "x_column": "...",
        "y_column": "...",
        "group_column": "...",
        "output_path": "chart.png",
        "title": "..."
    }

Output (to stdout JSON):
    {
        "status": "ok",
        "chart_path": "chart.png",
        "chart_type": "...",
        "rows_plotted": 1000,
        "file_size_bytes": 12345
    }
"""
import sys
import json
import os


def visualize(payload: dict) -> dict:
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")  # No display
    import matplotlib.pyplot as plt

    data_path = payload.get("data_path")
    if not data_path or not os.path.exists(data_path):
        raise ValueError(f"data_path missing or file not found: {data_path}")

    chart_type = payload.get("chart_type", "histogram")
    x_col = payload.get("x_column")
    y_col = payload.get("y_column")
    group_col = payload.get("group_column")
    output_path = payload.get("output_path", "/tmp/analysis_chart.png")
    title = payload.get("title", "")

    df = pd.read_csv(data_path)
    fig, ax = plt.subplots(figsize=(14, 5))

    if chart_type == "histogram":
        if not x_col or x_col not in df.columns:
            raise ValueError(f"x_column required for histogram: {x_col}")
        ax.hist(df[x_col].dropna(), bins=30, edgecolor="black")
        ax.set_xlabel(x_col)
        ax.set_ylabel("Frequency")
        if not title:
            title = f"Distribution of {x_col}"

    elif chart_type == "bar":
        if not x_col or not y_col:
            raise ValueError("x_column and y_column required for bar chart")
        agg = df.groupby(x_col)[y_col].sum().sort_values(ascending=False).head(20)
        agg.plot(kind="bar", ax=ax)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        if not title:
            title = f"{y_col} by {x_col}"

    elif chart_type == "line":
        if not x_col or not y_col:
            raise ValueError("x_column and y_column required for line chart")
        df_sorted = df.sort_values(x_col)
        ax.plot(df_sorted[x_col], df_sorted[y_col])
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        if not title:
            title = f"{y_col} over {x_col}"

    elif chart_type == "scatter":
        if not x_col or not y_col:
            raise ValueError("x_column and y_column required for scatter")
        ax.scatter(df[x_col], df[y_col], alpha=0.5)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        if not title:
            title = f"{y_col} vs {x_col}"

    elif chart_type == "subplots":
        # 2 subplots side by side — used by analysis workflow
        if not x_col or not y_col:
            raise ValueError("x_column and y_column required for subplots")
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        # Subplot 1: distribution
        axes[0].hist(df[y_col].dropna(), bins=30, edgecolor="black", color="steelblue")
        axes[0].set_xlabel(y_col)
        axes[0].set_ylabel("Frequency")
        axes[0].set_title(f"Distribution of {y_col}")
        # Subplot 2: bar of group means
        if group_col and group_col in df.columns:
            agg = df.groupby(group_col)[y_col].mean().sort_values(ascending=False).head(10)
            agg.plot(kind="bar", ax=axes[1], color="coral")
            axes[1].set_xlabel(group_col)
            axes[1].set_ylabel(f"Mean {y_col}")
            axes[1].set_title(f"Mean {y_col} by {group_col}")
        else:
            axes[1].hist(df[x_col].dropna(), bins=30, edgecolor="black", color="coral")
            axes[1].set_xlabel(x_col)
            axes[1].set_ylabel("Frequency")
            axes[1].set_title(f"Distribution of {x_col}")

    ax.set_title(title)
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {
        "status": "ok",
        "chart_path": output_path,
        "chart_type": chart_type,
        "rows_plotted": int(df.shape[0]),
        "file_size_bytes": os.path.getsize(output_path),
        "title": title,
    }


def main():
    try:
        payload = json.loads(sys.stdin.read())
        result = visualize(payload)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()