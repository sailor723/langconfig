#!/usr/bin/env python3
"""Generate a realistic e-commerce sales CSV for testing the data-analysis skill.

300 rows, 11 columns, with intentional patterns:
- Date range: 6 months
- 4 regions, 3 customer segments, 5 product categories
- Realistic correlations: Premium segment → higher amount, Electronics → higher amount
- Some missing values (5% ages, 3% emails)
- Some returns (~8% of orders)
- A few high-value outliers
"""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)  # reproducible

REGIONS = ["North America", "Europe", "Asia", "South America"]
SEGMENTS = ["Consumer", "Business", "Premium"]
CATEGORIES = ["Electronics", "Clothing", "Home & Garden", "Books", "Sports"]
PAYMENTS = ["Credit Card", "PayPal", "Debit Card", "Bank Transfer"]

PRODUCTS = {
    "Electronics":  [("Laptop Pro 15",        1299.99, 0.15),
                     ("Wireless Headphones",    89.99, 0.40),
                     ("Smart Watch",           249.99, 0.25),
                     ("USB-C Charger",          24.99, 0.20)],
    "Clothing":     [("Running Shoes",         119.99, 0.30),
                     ("Cotton T-Shirt",         19.99, 0.35),
                     ("Winter Jacket",         189.99, 0.20),
                     ("Jeans Classic",          59.99, 0.15)],
    "Home & Garden":[("Coffee Maker",         149.99, 0.25),
                     ("Garden Hose 50ft",       34.99, 0.30),
                     ("Bed Sheet Set",          79.99, 0.20),
                     ("Air Purifier",          299.99, 0.25)],
    "Books":        [("Python Programming",     39.99, 0.40),
                     ("Data Science Handbook",  49.99, 0.30),
                     ("Sci-Fi Novel",           14.99, 0.20),
                     ("Cookbook Italian",       24.99, 0.10)],
    "Sports":       [("Yoga Mat Premium",       49.99, 0.30),
                     ("Dumbbells Set",         199.99, 0.20),
                     ("Tennis Racket",         129.99, 0.25),
                     ("Basketball Official",    29.99, 0.25)],
}

def gen_row(i: int, start_date: datetime) -> dict:
    # Date with weekday bias (more sales Tue-Thu)
    days_offset = random.randint(0, 180)
    date = start_date + timedelta(days=days_offset)
    # Shift to weekday
    while date.weekday() >= 5:
        date += timedelta(days=1)

    customer_id = f"C{random.randint(1000, 9999)}"
    segment = random.choices(SEGMENTS, weights=[0.55, 0.30, 0.15])[0]
    region = random.choices(REGIONS, weights=[0.45, 0.30, 0.15, 0.10])[0]
    category = random.choice(CATEGORIES)
    product_name, base_price, weight = random.choices(PRODUCTS[category], weights=[w for _, _, w in PRODUCTS[category]])[0]

    # Premium customers buy more expensive items; Business buys in bulk
    if segment == "Premium":
        unit_price = round(base_price * random.uniform(1.0, 1.5), 2)
        quantity = random.choices([1, 2, 3, 4, 5], weights=[0.40, 0.30, 0.15, 0.10, 0.05])[0]
    elif segment == "Business":
        unit_price = round(base_price * random.uniform(0.9, 1.2), 2)
        quantity = random.choices([1, 2, 3, 5, 10, 20], weights=[0.30, 0.25, 0.20, 0.15, 0.07, 0.03])[0]
    else:  # Consumer
        unit_price = round(base_price * random.uniform(0.85, 1.1), 2)
        quantity = random.choices([1, 2, 3], weights=[0.70, 0.25, 0.05])[0]

    total = round(unit_price * quantity, 2)

    # Discount for bulk orders
    discount = 0.0
    if quantity >= 10:
        discount = round(total * 0.15, 2)
    elif quantity >= 5:
        discount = round(total * 0.08, 2)
    final_amount = round(total - discount, 2)

    # Returns: 8% baseline, but Consumer returns more often
    returned = random.random() < (0.12 if segment == "Consumer" else 0.05)

    payment = random.choices(PAYMENTS, weights=[0.55, 0.25, 0.15, 0.05])[0]

    # Missing values: 5% ages, 3% emails
    customer_age = random.randint(18, 75)
    if random.random() < 0.05:
        customer_age = ""
    customer_email = f"{customer_id.lower()}@{'gmail.com' if random.random() < 0.7 else 'company.com'}"
    if random.random() < 0.03:
        customer_email = ""

    # Outliers: 0.5% chance of very high amount
    if random.random() < 0.005:
        final_amount = round(final_amount * random.uniform(5, 15), 2)
        quantity = quantity * random.choice([5, 10, 20])

    return {
        "order_id":       f"ORD-{10000 + i:05d}",
        "order_date":     date.strftime("%Y-%m-%d"),
        "customer_id":    customer_id,
        "customer_age":   customer_age,
        "customer_email": customer_email,
        "segment":        segment,
        "region":         region,
        "product_category": category,
        "product_name":   product_name,
        "quantity":       quantity,
        "unit_price":     unit_price,
        "total_amount":   final_amount,
        "payment_method": payment,
        "returned":       "Yes" if returned else "No",
    }


def main():
    out = Path("/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/data/uploads/sales_2024.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    start_date = datetime(2024, 1, 1)

    rows = [gen_row(i, start_date) for i in range(300)]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")
    print(f"Size: {out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()