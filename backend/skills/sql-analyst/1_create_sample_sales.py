#!/usr/bin/env python3
"""
Step 1: SQLite Mock Database for sql-analyst skill testing.

Creates a realistic sales + inventory database: customers (10), products (10), orders (25).
"""
import sqlite3
import pathlib

DB_PATH = pathlib.Path(__file__).parent / "sample_sales.db"


def create_sample_db(db_path: str = str(DB_PATH)):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # --- Customers ---
    cursor.execute("DROP TABLE IF EXISTS customers")
    cursor.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            signup_date TEXT,
            status TEXT DEFAULT 'active',
            customer_tier TEXT DEFAULT 'bronze',
            city TEXT,
            country TEXT
        )
    """)
    customers = [
        (1, 'Alice Wang', 'alice@example.com', '2024-01-15', 'active', 'gold', 'Shanghai', 'China'),
        (2, 'Bob Smith', 'bob@example.com', '2024-03-20', 'active', 'silver', 'Tokyo', 'Japan'),
        (3, 'Carol Li', 'carol@example.com', '2024-06-10', 'active', 'platinum', 'Beijing', 'China'),
        (4, 'David Chen', 'david@example.com', '2024-09-05', 'inactive', 'bronze', 'Seoul', 'Korea'),
        (5, 'Eve Zhang', 'eve@example.com', '2025-01-01', 'active', 'gold', 'Shanghai', 'China'),
        (6, 'Frank Liu', 'frank@example.com', '2025-02-14', 'active', 'silver', 'Shenzhen', 'China'),
        (7, 'Grace Wu', 'grace@example.com', '2025-03-30', 'inactive', 'bronze', 'Hong Kong', 'China'),
        (8, 'Henry Kim', 'henry@example.com', '2025-05-01', 'active', 'gold', 'Busan', 'Korea'),
        (9, 'Ivy Tanaka', 'ivy@example.com', '2025-06-15', 'active', 'silver', 'Osaka', 'Japan'),
        (10, 'Jack Park', 'jack@example.com', '2025-07-20', 'active', 'bronze', 'Incheon', 'Korea'),
    ]
    cursor.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)",
        customers
    )

    # --- Products ---
    cursor.execute("DROP TABLE IF EXISTS products")
    cursor.execute("""
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT,
            unit_price REAL,
            unit_cost REAL,
            discontinued INTEGER DEFAULT 0
        )
    """)
    products = [
        (1, 'AI-Powered Analytics Pro', 'Software', 299.99, 80.00, 0),
        (2, 'Cloud Data Pipeline', 'Software', 199.99, 60.00, 0),
        (3, 'Smart Dashboard Lite', 'Software', 99.99, 30.00, 0),
        (4, 'Neural Network Starter Kit', 'Hardware', 499.99, 200.00, 0),
        (5, 'Quantum Computing Simulator', 'Software', 999.99, 400.00, 1),
        (6, 'Enterprise Security Suite', 'Software', 1499.99, 500.00, 0),
        (7, 'IoT Sensor Array', 'Hardware', 249.99, 100.00, 0),
        (8, 'Automated ML Pipeline', 'Software', 399.99, 150.00, 0),
        (9, 'Data Lake Storage 1TB', 'Infrastructure', 59.99, 20.00, 0),
        (10, 'GPU Computing Cluster', 'Hardware', 4999.99, 3000.00, 0),
    ]
    cursor.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?)",
        products
    )

    # --- Orders ---
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            product_id INTEGER,
            order_date TEXT,
            status TEXT DEFAULT 'pending',
            quantity INTEGER DEFAULT 1,
            total_amount REAL,
            sales_region TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
    """)
    orders = [
        (1, 1, 1, '2025-01-05', 'completed', 2, 599.98, 'east'),
        (2, 1, 3, '2025-01-05', 'completed', 1, 99.99, 'east'),
        (3, 2, 2, '2025-02-10', 'completed', 1, 199.99, 'west'),
        (4, 3, 4, '2025-03-15', 'completed', 1, 499.99, 'north'),
        (5, 3, 6, '2025-03-15', 'completed', 1, 1499.99, 'north'),
        (6, 5, 1, '2025-03-20', 'completed', 1, 299.99, 'east'),
        (7, 5, 8, '2025-03-20', 'completed', 2, 799.98, 'east'),
        (8, 6, 7, '2025-04-01', 'completed', 5, 1249.95, 'south'),
        (9, 8, 10, '2025-04-15', 'completed', 1, 4999.99, 'west'),
        (10, 1, 4, '2025-04-20', 'completed', 1, 499.99, 'east'),
        (11, 9, 2, '2025-05-01', 'completed', 1, 199.99, 'west'),
        (12, 9, 3, '2025-05-01', 'completed', 3, 299.97, 'west'),
        (13, 10, 9, '2025-05-10', 'completed', 10, 599.90, 'south'),
        (14, 2, 6, '2025-05-15', 'completed', 1, 1499.99, 'west'),
        (15, 3, 1, '2025-06-01', 'completed', 3, 899.97, 'north'),
        (16, 5, 7, '2025-06-10', 'completed', 2, 499.98, 'east'),
        (17, 6, 8, '2025-06-15', 'pending', 1, 399.99, 'south'),
        (18, 1, 9, '2025-06-20', 'pending', 5, 299.95, 'east'),
        (19, 4, 1, '2025-06-25', 'completed', 1, 299.99, 'north'),
        (20, 8, 4, '2025-07-01', 'completed', 2, 999.98, 'west'),
        (21, 10, 2, '2025-07-05', 'completed', 1, 199.99, 'south'),
        (22, 1, 6, '2025-07-10', 'cancelled', 1, 1499.99, 'east'),
        (23, 3, 8, '2025-07-15', 'completed', 1, 399.99, 'north'),
        (24, 5, 5, '2025-07-20', 'completed', 1, 999.99, 'east'),
        (25, 9, 7, '2025-07-25', 'pending', 3, 749.97, 'west'),
    ]
    cursor.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
        orders
    )

    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = create_sample_db()
    print(f"✅ Sample database created: {path}")

    # Print schema summary
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    for t in tables:
        cursor.execute(f"PRAGMA table_info({t[0]})")
        cols = cursor.fetchall()
        print(f"\n  📋 {t[0]} ({len(cols)} columns)")
        for c in cols:
            print(f"     {c[1]} ({c[2]})")
    conn.close()
