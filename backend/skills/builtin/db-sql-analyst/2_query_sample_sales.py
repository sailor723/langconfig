#!/usr/bin/env python3
"""
Step 2: Raw SQL Query — Layer 1 of the SQL analysis flow.

Directly query the sample_sales.db using sqlite3 to discover schema and data.
"""
import sqlite3
import pathlib

DB_PATH = pathlib.Path(__file__).parent / "sample_sales.db"


def query_schema(conn):
    """Step 1a: Discover all tables in the database."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print("Tables:", tables)
    return tables


def query_columns(conn, table_name):
    """Step 1b: Check column names and types for a given table."""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
    cols = [(r[1], r[2]) for r in cursor.fetchall()]

    # Also get row count
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]

    print(f"\n{table_name} ({count} rows):")
    for name, dtype in cols:
        print(f"  - {name} ({dtype})")


def top_products_by_revenue(conn):
    """Step 1c: Top 3 products by total revenue (completed orders only)."""
    cursor = conn.execute("""
        SELECT p.product_name,
               SUM(o.total_amount) AS revenue,
               SUM(o.quantity)     AS units_sold,
               COUNT(*)            AS order_count
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        WHERE o.status = 'completed'
        GROUP BY p.product_name
        ORDER BY revenue DESC
        LIMIT 3
    """)
    print("\nTop 3 Products by Revenue:")
    for r in cursor:
        print(f"  {r[0]:30s}  ${r[1]:>8.2f}  ({r[2]} units, {r[3]} orders)")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)

    # Step 1a: Discover tables
    tables = query_schema(conn)

    # Step 1b: Examine each table's structure
    for t in tables:
        query_columns(conn, t)

    # Step 1c: Business query — top 3 products by revenue
    top_products_by_revenue(conn)

    conn.close()
    print("\n✅ Layer 1 complete: raw SQL query works!")
