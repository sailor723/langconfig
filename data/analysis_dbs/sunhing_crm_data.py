"""
Generate per-order CRM data for Sun Hing Vision Group.

Replaces the old monthly-summary raw_crm with real order-level records.
~55 individual customer orders across 6 months (Sep 2026–Feb 2027).

Output: inserts into sunhing_kpi.db raw_crm table
"""

import sqlite3, pathlib, random

DB_DIR = pathlib.Path(__file__).parent
DB_PATH = DB_DIR / "sunhing_kpi.db"

# Customers (some retained, some churned during restructuring)
CUSTOMERS = [
    "Luxottica Group",  "Safilo Group",     "Marchon Eyewear",
    "Marcolin Group",   "De Rigo Vision",   "Fielmann AG",
    "EssilorLuxottica", "Warby Parker",     "Zenni Optical",
    "Specsavers",       "Vision Express",   "Alcon Vision",
    "Bausch + Lomb",    "CooperVision",     "Johnson & Johnson Vision",
    "Miyachi Global",   "Pioneer Optical",  "Horizon Frame Mfg",
    "Sunlight Optical", "Pearl Vision",
]

# Eco-partner subset
ECO_PARTNERS = {"Miyachi Global", "Pioneer Optical", "Horizon Frame Mfg",
                 "Sunlight Optical", "Pearl Vision"}

# Monthly order config to match original aggregated data
MONTH_CONFIG = [
    ("2026-09", 22, 7500, 15,  3, 98.0),  # (month, num_orders, total_value, lost_value, complaints, otif_pct)
    ("2026-10", 24, 7600, 60,  8, 96.0),
    ("2026-11", 25, 7950, 120, 12, 93.0),
    ("2026-12", 22, 8200, 150, 10, 94.0),
    ("2027-01", 20, 8800, 105, 6,  96.0),
    ("2027-02", 18, 9300, 55,  4,  97.0),
]

random.seed(42)

def generate_orders():
    orders = []
    order_counter = 1

    for month, n_orders, total_val, lost_val, complaints, otif in MONTH_CONFIG:
        # Build orders in this month
        month_orders = []
        customers_in_use = random.sample(CUSTOMERS, min(n_orders, len(CUSTOMERS)))

        # Decide which customers are "lost" this month (their orders are lost)
        lost_count = max(1, round(n_orders * (lost_val / total_val)))  # proportional
        lost_customers = set(random.sample(customers_in_use, min(lost_count, len(customers_in_use))))

        # Generate per-order values that sum up to ~total_val
        remaining_val = total_val
        remaining_orders = n_orders
        base_value = total_val // n_orders

        for i, cust in enumerate(customers_in_use):
            if i == n_orders - 1:
                # last order takes remaining
                val = remaining_val
            else:
                val = base_value + random.randint(-20, 30)
                val = max(10, min(val, remaining_val - (remaining_orders - 1) * 10))
            remaining_val -= val
            remaining_orders -= 1

            is_lost = cust in lost_customers
            # Assign complaints proportionally
            has_complaint = 0
            if complaints > 0 and random.random() < (complaints / n_orders * 1.5):
                has_complaint = 1
                complaints -= 1

            delivered_ot = 1
            if not is_lost:
                # ~otif% of orders delivered on time
                delivered_ot = 1 if random.random() < (otif / 100) else 0

            is_eco = cust in ECO_PARTNERS
            eco_ot = 1
            if is_eco and not is_lost:
                eco_ot = 1 if random.random() < 0.90 else 0  # eco-partners ~90% OTIF

            order_id = f"ORD-{month.replace('-','')}-{order_counter:03d}"
            order_counter += 1

            month_orders.append({
                "order_id": order_id,
                "customer_name": cust,
                "order_date": f"{month}-{random.randint(1,28):02d}",
                "order_value_wan": round(val, 1),
                "status": "lost" if is_lost else "completed",
                "delivered_on_time": delivered_ot,
                "client_complaint": has_complaint,
                "is_eco_partner_order": 1 if is_eco else 0,
                "eco_partner_delivery_on_time": eco_ot if is_eco else 0,
                "month": month,
            })

        orders.extend(month_orders)

    return orders


def recreate_crm_table(cursor):
    cursor.execute("DROP TABLE IF EXISTS raw_crm")
    cursor.execute("""
        CREATE TABLE raw_crm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            order_id TEXT NOT NULL,
            customer_name TEXT,
            order_date TEXT,
            order_value_wan REAL,
            status TEXT,
            delivered_on_time INTEGER,
            client_complaint INTEGER,
            is_eco_partner_order INTEGER,
            eco_partner_delivery_on_time INTEGER,
            month TEXT
        )
    """)


def insert_orders(cursor, orders):
    for o in orders:
        cursor.execute("""
            INSERT INTO raw_crm (company_id, order_id, customer_name, order_date,
                order_value_wan, status, delivered_on_time, client_complaint,
                is_eco_partner_order, eco_partner_delivery_on_time, month)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            1, o["order_id"], o["customer_name"], o["order_date"],
            o["order_value_wan"], o["status"], o["delivered_on_time"],
            o["client_complaint"], o["is_eco_partner_order"],
            o["eco_partner_delivery_on_time"], o["month"],
        ))


if __name__ == "__main__":
    orders = generate_orders()
    print(f"Generated {len(orders)} orders across {len(MONTH_CONFIG)} months")
    print(f"Total value: {sum(o['order_value_wan'] for o in orders):.0f}万HKD")

    # Verify: show monthly summary
    from collections import defaultdict
    by_month = defaultdict(list)
    for o in orders:
        by_month[o["month"]].append(o)

    for m in sorted(by_month.keys()):
        mo = by_month[m]
        total = sum(o["order_value_wan"] for o in mo)
        lost = sum(o["order_value_wan"] for o in mo if o["status"] == "lost")
        complaints = sum(o["client_complaint"] for o in mo)
        ot = sum(o["delivered_on_time"] for o in mo if o["status"] == "completed")
        total_completed = sum(1 for o in mo if o["status"] == "completed")
        otif = (ot / total_completed * 100) if total_completed else 0
        print(f"  {m}: {len(mo)} orders, {total:.0f}万 total, "
              f"{lost:.0f}万 lost ({lost/total*100:.1f}%), "
              f"{complaints} complaints, OTIF {otif:.0f}%")

    # Write to DB
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    recreate_crm_table(cursor)
    insert_orders(cursor, orders)
    conn.commit()

    # Verify DB
    count = cursor.execute("SELECT COUNT(*) FROM raw_crm").fetchone()[0]
    print(f"\nWritten to {DB_PATH}: {count} rows in raw_crm ✅")
    conn.close()
