"""
Initialize the sample SQLite database for the SQL Skills Assistant notebook.
Creates tables matching the sales_analytics and inventory_management skills,
and populates them with realistic sample data.
"""

import sqlite3
import os
from datetime import datetime, timedelta
import random

DB_PATH = os.path.join(os.path.dirname(__file__), "enterprise_data", "commerce.db")
random.seed(42)


def create_tables(conn: sqlite3.Connection):
    """Create all tables for sales and inventory schemas."""
    conn.executescript("""
        -- Sales schema
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            signup_date TEXT,
            status TEXT CHECK(status IN ('active', 'inactive')),
            customer_tier TEXT CHECK(customer_tier IN ('bronze', 'silver', 'gold', 'platinum'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(customer_id),
            order_date TEXT,
            status TEXT CHECK(status IN ('pending', 'completed', 'cancelled', 'refunded')),
            total_amount REAL,
            sales_region TEXT CHECK(sales_region IN ('north', 'south', 'east', 'west'))
        );

        CREATE TABLE IF NOT EXISTS order_items (
            item_id INTEGER PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id),
            product_id INTEGER,
            quantity INTEGER,
            unit_price REAL,
            discount_percent REAL DEFAULT 0
        );

        -- Inventory schema
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT,
            sku TEXT,
            category TEXT,
            unit_cost REAL,
            reorder_point INTEGER,
            discontinued INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS warehouses (
            warehouse_id INTEGER PRIMARY KEY,
            warehouse_name TEXT,
            location TEXT,
            capacity INTEGER
        );

        CREATE TABLE IF NOT EXISTS inventory (
            inventory_id INTEGER PRIMARY KEY,
            product_id INTEGER REFERENCES products(product_id),
            warehouse_id INTEGER REFERENCES warehouses(warehouse_id),
            quantity_on_hand INTEGER,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS stock_movements (
            movement_id INTEGER PRIMARY KEY,
            product_id INTEGER REFERENCES products(product_id),
            warehouse_id INTEGER REFERENCES warehouses(warehouse_id),
            movement_type TEXT CHECK(movement_type IN ('inbound', 'outbound', 'transfer', 'adjustment')),
            quantity INTEGER,
            movement_date TEXT,
            reference_number TEXT
        );
    """)
    conn.commit()


def seed_customers(conn: sqlite3.Connection):
    """Insert sample customer data."""
    customers = [
        (1, "Acme Corp", "acme@example.com", "2023-01-15", "active", "platinum"),
        (2, "Globex Inc", "globex@example.com", "2023-03-20", "active", "gold"),
        (3, "Initech", "initech@example.com", "2023-06-10", "active", "silver"),
        (4, "Hooli", "hooli@example.com", "2023-09-05", "active", "gold"),
        (5, "Massive Dynamic", "massive@example.com", "2024-01-01", "active", "platinum"),
        (6, "Soylent Corp", "soylent@example.com", "2024-02-15", "inactive", "bronze"),
        (7, "Wonka Industries", "wonka@example.com", "2024-04-20", "active", "silver"),
        (8, "Stark Industries", "stark@example.com", "2024-05-01", "active", "platinum"),
        (9, "Wayne Enterprises", "wayne@example.com", "2024-07-12", "active", "gold"),
        (10, "Cyberdyne Systems", "cyberdyne@example.com", "2024-08-30", "inactive", "bronze"),
        (11, "Oscorp", "oscorp@example.com", "2024-10-01", "active", "silver"),
        (12, "Umbrella Corp", "umbrella@example.com", "2024-11-15", "active", "gold"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers
    )
    conn.commit()


def seed_orders(conn: sqlite3.Connection):
    """Insert sample orders spanning last 6 months."""
    today = datetime(2026, 6, 13)
    orders = []
    order_items_batch = []
    statuses = ["completed", "completed", "completed", "pending", "cancelled", "refunded"]
    regions = ["north", "south", "east", "west"]

    for order_id in range(1, 61):
        customer_id = random.randint(1, 12)
        days_ago = random.randint(1, 180)
        order_date = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        status = random.choice(statuses)
        region = random.choice(regions)
        num_items = random.randint(1, 4)
        total = 0.0

        for item_idx in range(num_items):
            product_id = random.randint(1, 15)
            qty = random.randint(1, 10)
            price = round(random.uniform(10, 500), 2)
            discount = round(random.uniform(0, 0.2), 2) if random.random() > 0.5 else 0
            line_total = qty * price * (1 - discount)
            total += line_total
            order_items_batch.append((
                len(order_items_batch) + 1,
                order_id,
                product_id,
                qty,
                price,
                discount,
            ))

        # Make some orders high-value for interesting queries
        if random.random() > 0.85:
            total = round(random.uniform(1200, 5000), 2)

        orders.append((order_id, customer_id, order_date, status, round(total, 2), region))

    conn.executemany(
        "INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?, ?, ?)", orders
    )
    conn.executemany(
        "INSERT OR IGNORE INTO order_items VALUES (?, ?, ?, ?, ?, ?)",
        order_items_batch,
    )
    conn.commit()


def seed_products(conn: sqlite3.Connection):
    """Insert sample product data."""
    products = [
        (1, "Widget Alpha", "WGT-001", "Widgets", 8.50, 100, 0),
        (2, "Widget Beta", "WGT-002", "Widgets", 12.00, 80, 0),
        (3, "Gadget X", "GDG-001", "Gadgets", 25.00, 50, 0),
        (4, "Gadget Y Pro", "GDG-002", "Gadgets", 45.00, 30, 0),
        (5, "Super Widget", "WGT-003", "Widgets", 18.75, 60, 0),
        (6, "Mega Gadget", "GDG-003", "Gadgets", 99.99, 20, 0),
        (7, "Component A", "CMP-001", "Components", 3.50, 500, 0),
        (8, "Component B", "CMP-002", "Components", 5.25, 400, 0),
        (9, "Component C", "CMP-003", "Components", 7.00, 300, 0),
        (10, "Legacy Widget", "WGT-004", "Widgets", 15.00, 50, 1),
        (11, "Deluxe Gadget", "GDG-004", "Gadgets", 150.00, 10, 0),
        (12, "Eco Widget", "WGT-005", "Widgets", 22.00, 40, 0),
        (13, "Smart Component", "CMP-004", "Components", 12.50, 200, 0),
        (14, "Mini Gadget", "GDG-005", "Gadgets", 35.00, 25, 0),
        (15, "Pro Widget Max", "WGT-006", "Widgets", 45.00, 15, 0),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", products
    )
    conn.commit()


def seed_warehouses(conn: sqlite3.Connection):
    """Insert sample warehouse data."""
    warehouses = [
        (1, "North Region DC", "Chicago, IL", 10000),
        (2, "South Region DC", "Atlanta, GA", 8000),
        (3, "West Region DC", "Los Angeles, CA", 12000),
        (4, "East Region DC", "Newark, NJ", 9000),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO warehouses VALUES (?, ?, ?, ?)", warehouses
    )
    conn.commit()


def seed_inventory(conn: sqlite3.Connection):
    """Insert sample inventory data with some products below reorder point."""
    inventory_data = []
    today = datetime(2026, 6, 13).strftime("%Y-%m-%d")

    for product_id in range(1, 16):
        for warehouse_id in range(1, 5):
            # Some products have low stock to trigger reorder alerts
            if product_id in [3, 6, 11, 15] and warehouse_id == 1:
                qty = random.randint(0, 5)  # Below reorder point
            elif product_id == 7:
                qty = random.randint(1, 50)  # Well below reorder point of 500
            elif product_id in [10]:
                qty = 0  # Discontinued, no stock
            else:
                qty = random.randint(50, 300)
            inventory_data.append((
                len(inventory_data) + 1,
                product_id,
                warehouse_id,
                qty,
                today,
            ))

    conn.executemany(
        "INSERT OR IGNORE INTO inventory VALUES (?, ?, ?, ?, ?)", inventory_data
    )
    conn.commit()


def seed_stock_movements(conn: sqlite3.Connection):
    """Insert sample stock movement records."""
    movements = []
    today = datetime(2026, 6, 13)
    types = ["inbound", "outbound", "outbound", "inbound", "adjustment"]

    for i in range(1, 101):
        product_id = random.randint(1, 15)
        warehouse_id = random.randint(1, 4)
        mov_type = random.choice(types)
        days_ago = random.randint(1, 180)
        mov_date = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        qty = random.randint(-50, 100)
        if qty == 0:
            qty = 10
        ref = f"REF-{mov_type[:3].upper()}-{i:04d}"
        movements.append((i, product_id, warehouse_id, mov_type, qty, mov_date, ref))

    conn.executemany(
        "INSERT OR IGNORE INTO stock_movements VALUES (?, ?, ?, ?, ?, ?, ?)",
        movements,
    )
    conn.commit()


def init_db():
    """Initialize the database and seed all data."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    create_tables(conn)
    seed_customers(conn)
    seed_orders(conn)
    seed_products(conn)
    seed_warehouses(conn)
    seed_inventory(conn)
    seed_stock_movements(conn)

    conn.close()
    print(f"Database initialized: {DB_PATH}")
    print(f"  Tables: customers, orders, order_items, products, warehouses, inventory, stock_movements")


if __name__ == "__main__":
    init_db()
