#!/usr/bin/env python3
"""
Profile a pandas DataFrame: shape, types, missing values, descriptive stats.

Inputs (from stdin JSON):
    {
        "data_path": "path/to/data.csv",  # OR
        "dataframe_json": "..."  # base64-encoded pickle or JSON
    }

Output (to stdout JSON):
    {
        "status": "ok",
        "shape": [rows, cols],
        "columns": [...],
        "dtypes": {...},
        "missing": {"col1": 5, "col2": 0, ...},
        "missing_pct": {...},
        "describe": {...numeric stats...},
        "categorical_distributions": {...}
    }
"""
import sys
import json
import io


def load_dataframe(payload: dict):
    """Load a DataFrame from either a CSV path or inline JSON rows."""
    import pandas as pd

    if "data_path" in payload:
        return pd.read_csv(payload["data_path"])
    elif "rows" in payload:
        return pd.DataFrame(payload["rows"])
    else:
        raise ValueError("Either data_path or rows required")


def profile(df) -> dict:
    import pandas as pd
    import numpy as np

    # Shape and dtypes
    shape = [int(df.shape[0]), int(df.shape[1])]
    columns = list(df.columns)
    dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}

    # Missing values
    missing = {col: int(df[col].isnull().sum()) for col in columns}
    missing_pct = {
        col: round(int(df[col].isnull().sum()) / max(int(df.shape[0]), 1) * 100, 2)
        for col in columns
    }

    # Numeric describe
    describe = {}
    try:
        desc_df = df.describe(include="all").fillna("")
        describe = desc_df.to_dict()
        # Convert numpy types to native Python
        for col in describe:
            describe[col] = {k: _to_native(v) for k, v in describe[col].items()}
    except Exception:
        pass

    # Categorical distributions (top 5 per column)
    cat_distributions = {}
    for col in columns:
        if df[col].dtype == "object" or str(df[col].dtype) == "category":
            top = df[col].value_counts().head(5).to_dict()
            cat_distributions[col] = {str(k): int(v) for k, v in top.items()}

    return {
        "status": "ok",
        "shape": shape,
        "columns": columns,
        "dtypes": dtypes,
        "missing": missing,
        "missing_pct": missing_pct,
        "describe": describe,
        "categorical_distributions": cat_distributions,
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
        df = load_dataframe(payload)
        result = profile(df)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()