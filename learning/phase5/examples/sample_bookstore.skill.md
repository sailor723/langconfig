---
name: sample-bookstore
description: >-
  Bookstore sales data. Understand book sales across genres, stores, and managers over a 2-week period.
tags: [data-analysis, books, retail, bookstore, sales]
triggers:
  - "when user uploaded sample_bookstore.csv"
  - "when user asks about bookstore data"
  - "when user wants to analyze book sales"
allowed-tools: [read_file, execute, save_analysis_result]
author: User
---

# Sample Bookstore — Data Context

Companion skill for `sample_bookstore.csv`. Use alongside the system `data-analysis` skill.

## Dataset Overview

A small independent bookstore chain's sales across 3 stores over roughly 2 weeks (Feb 3-14, 2025). 30 transactions.

## Column Definitions

| Column | Type | Meaning | Example Values |
|---|---|---|---|
| `Date` | datetime | Sale date | 2025-02-03 |
| `Book` | categorical | Book title | The Midnight Library, Atomic Habits |
| `Genre` | categorical | Book genre | Fiction, Self-Help, Science Fiction, Non-Fiction |
| `Author` | categorical | Author name | Matt Haig, James Clear |
| `Copies Sold` | integer | Number of copies sold | 12, 20, 8 |
| `Unit Price` | float | Price per copy (USD) | 18.99, 22.50, 14.99 |
| `Revenue` | float | Copies Sold x Unit Price (USD) | 227.88, 450.00 |
| `Store` | categorical | Store location | Downtown, Eastside, Westside |
| `Manager` | categorical | Store manager | Emma Wilson, James Park, Lisa Chen |

## Business Logic

- **Revenue** is pre-computed as `Copies Sold x Unit Price`. Verify this when analyzing.
- **Genres**: Fiction, Self-Help, Science Fiction, Non-Fiction
- **Period**: February 3-14, 2025 (weekdays only - no weekend data)
- **3 stores**: Downtown (Emma), Eastside (James), Westside (Lisa)
- **Bestseller**: Atomic Habits ($22.50) has the highest unit price in Self-Help and sells consistently well
- **Valentine's Day (Feb 14)**: Higher volume observed — likely gift purchases

## Common Analysis Questions

1. "Which book generated the most revenue overall?"
2. "Which store has the highest total sales?"
3. "What is the daily revenue trend across the period?"
4. "Which genre performs best by total revenue?"
5. "How do copies sold and unit price correlate?"
6. "Which manager's store performed best?"

## Sample SQL

```sql
-- Total revenue by book
SELECT Book, SUM(Revenue) as total_revenue
FROM bookstore_data
GROUP BY Book
ORDER BY total_revenue DESC;

-- Revenue by store
SELECT Store, Manager, SUM(Revenue) as total_revenue
FROM bookstore_data
GROUP BY Store
ORDER BY total_revenue DESC;

-- Daily revenue trend
SELECT Date, SUM(Revenue) as daily_revenue
FROM bookstore_data
GROUP BY Date
ORDER BY Date;

-- Revenue by genre
SELECT Genre, SUM(Revenue) as total_revenue,
       SUM("Copies Sold") as total_copies
FROM bookstore_data
GROUP BY Genre
ORDER BY total_revenue DESC;

-- Price vs volume correlation
SELECT Book, Genre, "Unit Price", SUM("Copies Sold") as total_copies
FROM bookstore_data
GROUP BY Book
ORDER BY total_copies DESC;
```

## Chart Configuration

| Section | Type | Dimension | Metric |
|---|---|---|---|
| Revenue by Book | bar | Book | Revenue |
| Revenue by Store | pie | Store | Revenue |
| Daily Revenue Trend | line | Date | Revenue |
| Revenue by Genre | bar | Genre | Revenue |
| Sales Performance by Store | horizontal_bar | Store | Revenue |
| Unit Price vs Copies Sold | scatter | Unit Price | Copies Sold |

## Edge Cases

- Column names with spaces (`Copies Sold`, `Unit Price`) must be quoted in SQL.
- Revenue should equal `Copies Sold x Unit Price` exactly - flag any deviation.
- `Date` is a string in ISO format - cast to datetime for time-series operations.
- Only 30 rows - small-sample caveats apply.
- Weekday-only data - daily trend will show weekend gaps.
- The Subtle Art of Not Giving a F*ck has an asterisk — handle with care.
