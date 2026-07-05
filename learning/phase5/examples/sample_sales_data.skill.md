---
name: sample-sales-data
description: >-
  Sales data companion skill. Understands Apple product sales across regions, categories, and sales reps.
tags: [data-analysis, sales, apple-products, retail, regional-sales]
triggers:
  - "when user uploaded sample_sales_data.csv"
  - "when user asks about sales data"
  - "when user wants to analyze product sales"
allowed-tools: [read_file, execute, save_analysis_result]
author: User
---

# Sample Sales Data — Data Context

Companion skill for `sample_sales_data.csv`. Use alongside the system `data-analysis` skill.

## Dataset Overview

Apple product sales across 4 regions over roughly 3 weeks (Jan 6-24, 2025). 30 transactions.

## Column Definitions

| Column | Type | Meaning | Example Values |
|---|---|---|---|
| `Date` | datetime | Transaction date | 2025-01-06 |
| `Product` | categorical | Product name | MacBook Pro 16, iPhone 16 Pro, AirPods Pro |
| `Category` | categorical | Product line | Mobile, Audio, Tablets, Wearables |
| `Units Sold` | integer | Quantity sold | 3, 15, 8 |
| `Unit Price` | float | Price per unit (USD) | 2499, 249, 799 |
| `Revenue` | float | Units Sold x Unit Price (USD) | 7497, 3735 |
| `Region` | categorical | Sales territory | North, South, East, West |
| `Sales Rep` | categorical | Who closed the sale | Alice Chen, Bob Smith |

## Business Logic

- **Revenue** is pre-computed as `Units Sold x Unit Price`. Verify this when analyzing.
- **Categories**: Mobile (MacBook, iPhone), Audio (AirPods), Tablets (iPad), Wearables (Apple Watch, Vision Pro)
- **Period**: January 6-24, 2025 (weekdays only - no weekend data)
- **Price tiers**: Premium (Apple Vision Pro $3499, MacBook Pro $2499), Mid-range (iPhone $899-$1499, iPad $599-$1099), Accessory (AirPods $249, Watch SE $249)
- High-price items tend to have low unit counts; accessories sell in higher volumes

## Common Analysis Questions

1. "Which product generated the most revenue overall?"
2. "Which region has the highest total sales?"
3. "What is the daily revenue trend?"
4. "Which sales rep performed best?"
5. "What is the average order value by category?"
6. "How do unit price and units sold correlate?"

## Sample SQL

```sql
-- Total revenue by product
SELECT Product, SUM(Revenue) as total_revenue
FROM sales_data
GROUP BY Product
ORDER BY total_revenue DESC;

-- Revenue by region
SELECT Region, SUM(Revenue) as total_revenue
FROM sales_data
GROUP BY Region
ORDER BY total_revenue DESC;

-- Daily revenue trend
SELECT Date, SUM(Revenue) as daily_revenue
FROM sales_data
GROUP BY Date
ORDER BY Date;

-- Top sales rep by total revenue
SELECT "Sales Rep", SUM(Revenue) as total_revenue
FROM sales_data
GROUP BY "Sales Rep"
ORDER BY total_revenue DESC;

-- Average order value by category
SELECT Category,
       AVG(Revenue) as avg_revenue,
       SUM("Units Sold") as total_units
FROM sales_data
GROUP BY Category
ORDER BY avg_revenue DESC;
```

## Edge Cases

- Column names with spaces (`Units Sold`, `Unit Price`, `Sales Rep`) must be quoted in SQL.
- Revenue should equal `Units Sold x Unit Price` exactly - flag any deviation.
- `Date` is a string in ISO format - cast to datetime for time-series operations.
- Only 30 rows - small-sample caveats apply.
- Weekday-only data - daily trend will show weekend gaps.
