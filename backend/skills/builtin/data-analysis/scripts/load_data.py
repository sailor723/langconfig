#!/usr/bin/env python3
"""
Load data from CSV or SQL database.

Inputs (from stdin JSON):
    {"source_type": "csv", "file_path": "path/to/file.csv"}
    {"source_type": "sql", "query": "SELECT ...", "connection_string": "..."}

Output (to stdout JSON):
    {
        "status": "ok",
        "row_count": 1000,
        "columns": ["col1", "col2", ...],
        "dtypes": {"col1": "int64", ...},
        "data_preview": [...first 5 rows...],
        "data_id": "load_<timestamp>"
    }
"""
import sys
import json
import os


def load_from_csv(file_path: str) -> dict:
    import pandas as pd
    df = pd.read_csv(file_path)
    return _summarize(df, source=f"csv:{file_path}")


def load_from_sql(query: str, connection_string: str) -> dict:
    import pandas as pd
    from sqlalchemy import create_engine
    engine = create_engine(connection_string)
    df = pd.read_sql(query, engine)
    return _summarize(df, source=f"sql:{query[:50]}...")


def _summarize(df, source: str) -> dict:
    import time
    return {
        "status": "ok",
        "source": source,
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "data_preview": df.head(5).to_dict(orient="records"),
        "data_id": f"load_{int(time.time() * 1000)}",
    }


def main():
    try:
        payload = json.loads(sys.stdin.read())
        source_type = payload.get("source_type", "csv")

        if source_type == "csv":
            file_path = payload.get("file_path")
            if not file_path:
                raise ValueError("file_path required for csv source")
            result = load_from_csv(file_path)
        elif source_type == "sql":
            query = payload.get("query")
            conn_str = payload.get("connection_string") or os.environ.get(
                "DATABASE_URL",
                "postgresql://langconfig:langconfig_dev@localhost:5433/langconfig",
            )
            if not query:
                raise ValueError("query required for sql source")
            result = load_from_sql(query, conn_str)
        else:
            raise ValueError(f"Unknown source_type: {source_type}")

        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()