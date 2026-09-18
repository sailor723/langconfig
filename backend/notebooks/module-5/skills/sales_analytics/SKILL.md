---
name: sales_analytics
description: Database schema and business logic for sales data analysis including customers, orders, and revenue.
---

# Sales Analytics Schema

## Data Source

**Backend**: PostgreSQL database `commerce.db` with 3 tables (customers, orders, order_items).
Connection via `database_url` from `.env`.

Sample query result (top customers by revenue):
```sql
SELECT c.customer_id, c.name, SUM(o.total_amount) AS total_revenue
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
GROUP BY c.customer_id, c.name
ORDER BY total_revenue DESC
LIMIT 5;
```

## Tables

### customers
- customer_id (PRIMARY KEY, integer)
- name (varchar)
- email (varchar)
- signup_date (date)
- status (enum: active/inactive)
- customer_tier (enum: bronze/silver/gold/platinum)

### orders
- order_id (PRIMARY KEY, integer)
- customer_id (FOREIGN KEY -> customers)
- order_date (date)
- status (enum: pending/completed/cancelled/refunded)
- total_amount (decimal, USD)
- sales_region (enum: north/south/east/west)

### order_items
- item_id (PRIMARY KEY, integer)
- order_id (FOREIGN KEY -> orders)
- product_id (integer)
- quantity (integer)
- unit_price (decimal, USD)
- discount_percent (decimal 0-100)

## Column Metadata

| Table | Column | Data Type | Semantic | Usage |
|---|---|---|---|---|
| customers | customer_id | integer PK | Unique customer identifier | JOIN key |
| customers | status | enum | Account standing — drives "active" rule | WHERE in active-customer queries |
| customers | customer_tier | enum | Loyalty level (drives CLV weighting) | GROUP BY for tier analysis |
| customers | signup_date | date | When customer joined | Date math for active-customer rule |
| orders | order_id | integer PK | Unique order identifier | JOIN key |
| orders | status | enum | Order lifecycle state | **MUST filter to 'completed' for revenue** |
| orders | total_amount | decimal | Final order value (after discounts) | SUM for revenue |
| orders | sales_region | enum | Geographic region (4-way split) | GROUP BY for regional analysis |
| order_items | quantity | integer | Units in this line item | SUM per order |
| order_items | unit_price | decimal | Per-unit price | Multiplier in line item total |
| order_items | discount_percent | decimal | Line-level discount (0-100) | Apply BEFORE adding to order total |

## Business Logic

**Active customers**: `status = 'active' AND signup_date <= CURRENT_DATE - INTERVAL '90 days'`
Rationale: a customer must have signed up at least 90 days ago AND still have an active subscription.

**Revenue calculation**: Only count orders with `status = 'completed'`. Use `total_amount` from orders table, which already accounts for discounts (don't recompute from order_items).
Rationale: order_items discounts may not match the order's final total (some line items have no discount).

**Customer lifetime value (CLV)**: Sum of all `total_amount` from orders with `status = 'completed'` for a customer.

**High-value orders**: Orders with `total_amount > 1000`.

**Order status lifecycle**: `pending → completed | cancelled | refunded`. Refunded orders DO NOT count as revenue.

## Few-shot Examples

### Example 1: Top 10 customers by revenue in the last quarter

```sql
SELECT
  c.customer_id,
  c.name,
  c.customer_tier,
  SUM(o.total_amount) as total_revenue
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
  AND o.order_date >= CURRENT_DATE - INTERVAL '3 months'
GROUP BY c.customer_id, c.name, c.customer_tier
ORDER BY total_revenue DESC
LIMIT 10;
```

### Example 2: CLV per customer tier

```sql
SELECT c.customer_tier, SUM(o.total_amount) AS total_revenue, COUNT(DISTINCT c.customer_id) AS customer_count
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
GROUP BY c.customer_tier
ORDER BY total_revenue DESC;
```

### Example 3: Revenue by region

```sql
SELECT sales_region, SUM(total_amount) AS revenue
FROM orders
WHERE status = 'completed'
GROUP BY sales_region
ORDER BY revenue DESC;
```

## Chart Generation

When the user asks for a chart or visualization, use the `generate_chart` tool.

**How to use generate_chart:**
1. First, write a SQL query that returns **2 columns**: label (1st column) and value (2nd column)
2. Call `generate_chart(sql, chart_type, title)` with the query
3. Example: After finding top customers by revenue, call `generate_chart` with a query like `SELECT name, total_revenue FROM ...` and `chart_type="bar"`

**Recommended chart types by scenario:**
- **bar**: Comparing values across categories (e.g., revenue by customer, revenue by region)
- **pie**: Showing percentage breakdowns (e.g., revenue by product category, customer tier distribution)
- **line**: Showing trends over time
- **horizontal_bar**: Many categories (6+ items) where labels are long

## Edge Cases & Pitfalls

### 1. Including non-completed orders in revenue
❌ `SELECT SUM(total_amount) FROM orders` → overcounts (includes pending, refunded)
✅ `WHERE status = 'completed'` (mandatory filter)

### 2. Computing order total from order_items
❌ `SUM(quantity * unit_price * (1 - discount_percent/100))` from order_items
✅ Use `orders.total_amount` directly — order-level discounts and adjustments may differ

### 3. Active customer rule
❌ `WHERE status = 'active'` only — includes brand-new customers
✅ `WHERE status = 'active' AND signup_date <= CURRENT_DATE - INTERVAL '90 days'` — only established customers

### 4. JOIN order_items in revenue queries
❌ Joining order_items causes row multiplication (one order has many items)
✅ Aggregate orders FIRST, then optionally join for product-level analysis

### 5. NULL signup_date
Some legacy customers have `signup_date = NULL`.
✅ `WHERE signup_date <= CURRENT_DATE - INTERVAL '90 days'` excludes NULLs (NULL comparison returns NULL, not TRUE)
❌ Treating NULL as "old enough" — overstates active customer base

### 6. Refunded orders and revenue
Refunded orders have `status = 'refunded'` (NOT 'cancelled').
✅ Filter `WHERE status = 'completed'` excludes both.
❌ Filtering only `status != 'cancelled'` includes refunds.
