#!/usr/bin/env python3
"""
Explore the PostgreSQL database schema — list all tables and columns.

Inputs (from stdin JSON):
    {"connection_string": "postgresql://..."}   # optional, defaults to DATABASE_URL env

Output (to stdout JSON):
    {
        "status": "ok",
        "table_count": 12,
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "type": "INTEGER"},
                    {"name": "email", "type": "VARCHAR"}
                ]
            },
            ...
        ]
    }
"""
import sys
import json
import os


def explore(payload: dict) -> dict:
    conn_str = payload.get("connection_string") or os.environ.get(
        "DATABASE_URL",
        "postgresql://langconfig:langconfig_dev@localhost:5433/langconfig",
    )

    from sqlalchemy import create_engine, inspect
    engine = create_engine(conn_str)
    inspector = inspect(engine)

    tables = []
    for table_name in sorted(inspector.get_table_names()):
        columns = [
            {"name": col["name"], "type": str(col["type"])}
            for col in inspector.get_columns(table_name)
        ]
        tables.append({"name": table_name, "column_count": len(columns), "columns": columns})

    return {"status": "ok", "table_count": len(tables), "tables": tables}


def main():
    try:
        payload = json.loads(sys.stdin.read())
        result = explore(payload)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()