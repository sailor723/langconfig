#!/usr/bin/env python3
"""
Step 3: Layer 2 — The sqlite_execute tool function.

This wraps raw SQL with safety checks + formatted output.
It's the deterministic bridge the LLM calls instead of raw sqlite3.
"""
import sqlite3
import pathlib

DB_PATH = pathlib.Path(__file__).parent / "sample_sales.db"


def sqlite_execute(sql: str, db_path: str = ":memory:") -> str:
    """
    Execute a read-only SQL query on a SQLite database.

    This is the EXACT same logic as in backend/tools/native_tools.py#L3334.

    Safety rules:
    - Only SELECT queries allowed (blocks INSERT/UPDATE/DELETE/DROP/ALTER/CREATE)
    - Auto-limited to 200 rows
    - Formatted as aligned table for LLM readability

    Args:
        sql: SELECT SQL query to execute
        db_path: Path to SQLite DB file

    Returns:
        Formatted query results or error message
    """
    # --- Safety: block all non-SELECT statements ---
    sql_stripped = sql.strip().strip(";").strip()
    sql_lower = sql_stripped.lower()
    blocked_keywords = [
        "insert", "update", "delete", "drop", "alter",
        "create", "replace", "truncate", "exec",
    ]

    first_word = sql_lower.split()[0] if sql_lower.split() else ""
    if first_word in blocked_keywords:
        return (
            f"❌ BLOCKED: Only SELECT queries are allowed. "
            f"Got: '{sql_stripped[:100]}'"
        )

    # --- Execute ---
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM ({sql_stripped}) LIMIT 200")
        rows = cursor.fetchall()
        col_names = (
            [desc[0] for desc in cursor.description]
            if cursor.description else []
        )

        if not rows:
            conn.close()
            return "✅ Query executed. No rows returned (empty result)."

        # --- Format as aligned table ---
        widths = [len(c) for c in col_names]
        for row in rows:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(str(val)))

        header = " | ".join(c.ljust(w) for c, w in zip(col_names, widths))
        sep = "-+-".join("-" * w for w in widths)
        body = "\n".join(
            " | ".join(str(v).ljust(w) for v, w in zip(row, widths))
            for row in rows[:50]  # Max 50 rows in display output
        )

        summary = f"✅ {len(rows)} row(s) returned"
        conn.close()
        return f"{summary}\n\n{header}\n{sep}\n{body}"

    except Exception as e:
        return f"❌ SQL Error: {e}"


if __name__ == "__main__":
    print("=" * 65)
    print("  Layer 2: sqlite_execute tool — Safety + Formatting")
    print("=" * 65)

    # --- Test 1: Valid SELECT ---
    print("\n>>> Test 1: SELECT with JOIN, GROUP BY, ORDER BY")
    result = sqlite_execute(
        """
        SELECT p.product_name,
               SUM(o.total_amount) AS revenue,
               SUM(o.quantity)     AS units_sold
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        WHERE o.status = 'completed'
        GROUP BY p.product_name
        ORDER BY revenue DESC
        LIMIT 3
        """,
        str(DB_PATH),
    )
    print(result)

    # --- Test 2: Safety block ---
    print("\n>>> Test 2: BLOCKED — DROP TABLE")
    result = sqlite_execute("DROP TABLE orders", str(DB_PATH))
    print(result)

    # --- Test 3: Safety block ---
    print("\n>>> Test 3: BLOCKED — DELETE")
    result = sqlite_execute(
        "DELETE FROM orders WHERE order_id = 1", str(DB_PATH)
    )
    print(result)

    # --- Test 4: Schema discovery ---
    print("\n>>> Test 4: Schema discovery (sqlite_master)")
    result = sqlite_execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'",
        str(DB_PATH),
    )
    print(result)

    print("\n✅ Layer 2 complete: sqlite_execute tool works deterministically!")
