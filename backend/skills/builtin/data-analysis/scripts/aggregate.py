#!/usr/bin/env python3
"""
Aggregate data: group by + sum/mean/count, correlations, time series trends.

Inputs (from stdin JSON):
    {
        "data_path": "...",
        "group_by": "category_col",
        "agg_column": "revenue_col",
        "agg_funcs": ["sum", "mean", "count"],
        "top_n": 10
    }

Output (to stdout JSON):
    {
        "status": "ok",
        "groups": [{"key": "...", "sum": ..., "mean": ..., "count": ...}, ...],
        "correlations": {...},
        "top_n": [...]
    }
"""
import sys
import json
import pandas as pd


def aggregate(payload: dict) -> dict:
    df = _load_df(payload)

    group_by = payload.get("group_by")
    agg_column = payload.get("agg_column")
    agg_funcs = payload.get("agg_funcs", ["sum", "mean", "count"])
    top_n = payload.get("top_n", 10)

    result = {"status": "ok"}

    # Group aggregation
    if group_by and agg_column and group_by in df.columns:
        agg_dict = {agg_column: agg_funcs}
        grouped = df.groupby(group_by).agg(agg_dict).round(2)
        # Flatten multi-index columns
        grouped.columns = ["_".join(c).strip("_") for c in grouped.columns]
        grouped = grouped.reset_index()
        # Sort by first agg func descending
        sort_col = f"{agg_column}_{agg_funcs[0]}" if agg_funcs else None
        if sort_col and sort_col in grouped.columns:
            grouped = grouped.sort_values(sort_col, ascending=False)
        result["groups"] = grouped.head(top_n).to_dict(orient="records")

    # Numeric correlations
    numeric_df = df.select_dtypes(include="number")
    if numeric_df.shape[1] >= 2:
        corr = numeric_df.corr().round(3)
        result["correlations"] = corr.to_dict()

    # Time series if date column present
    date_col = payload.get("date_col")
    if date_col and date_col in df.columns:
        try:
            df_ts = df.copy()
            df_ts[date_col] = pd.to_datetime(df_ts[date_col])
            df_ts = df_ts.set_index(date_col)
            if agg_column and agg_column in df_ts.columns:
                freq = payload.get("freq", "D")
                ts = df_ts.resample(freq)[agg_column].sum()
                result["time_series"] = {
                    "date_col": date_col,
                    "metric_col": agg_column,
                    "freq": freq,
                    "points": [{"date": str(d), "value": float(v)} for d, v in ts.items()],
                }
        except Exception as e:
            result["time_series_error"] = str(e)

    return result


def _load_df(payload: dict) -> "pd.DataFrame":
    if "data_path" in payload:
        return pd.read_csv(payload["data_path"])
    elif "rows" in payload:
        return pd.DataFrame(payload["rows"])
    raise ValueError("data_path or rows required")


def main():
    try:
        payload = json.loads(sys.stdin.read())
        result = aggregate(payload)
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()