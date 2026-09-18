---
name: inventory_management
description: Database schema and business logic for inventory tracking including products, warehouses, and stock levels.
---

# Inventory Management Schema

## Data Source

**Backend**: PostgreSQL database (same `commerce.db` as `sales_analytics`).
Connection via `database_url` from `.env`.

Sample query result (products needing reorder):
```sql
SELECT p.product_id, p.product_name, SUM(i.quantity_on_hand) AS total_stock, p.reorder_point
FROM products p
JOIN inventory i ON p.product_id = i.product_id
WHERE p.discontinued = false
GROUP BY p.product_id, p.product_name, p.reorder_point
HAVING SUM(i.quantity_on_hand) <= p.reorder_point;
```

## Tables

### products
- product_id (PRIMARY KEY, integer)
- product_name (varchar)
- sku (varchar, unique stock keeping unit)
- category (varchar)
- unit_cost (decimal, USD)
- reorder_point (integer, minimum stock level before reordering)
- discontinued (boolean)

### warehouses
- warehouse_id (PRIMARY KEY, integer)
- warehouse_name (varchar)
- location (varchar)
- capacity (integer, max units)

### inventory
- inventory_id (PRIMARY KEY, integer)
- product_id (FOREIGN KEY -> products)
- warehouse_id (FOREIGN KEY -> warehouses)
- quantity_on_hand (integer)
- last_updated (timestamp)

### stock_movements
- movement_id (PRIMARY KEY, integer)
- product_id (FOREIGN KEY -> products)
- warehouse_id (FOREIGN KEY -> warehouses)
- movement_type (enum: inbound/outbound/transfer/adjustment)
- quantity (integer, signed: positive=inbound, negative=outbound)
- movement_date (timestamp)
- reference_number (varchar, optional PO/so_number)

## Column Metadata

| Table | Column | Data Type | Semantic | Usage |
|---|---|---|---|---|
| products | product_id | integer PK | Unique product identifier | JOIN key |
| products | sku | varchar unique | Stock keeping unit (alternate ID) | Lookup by SKU code |
| products | unit_cost | decimal | Cost basis for valuation | Multiplier in stock value calc |
| products | reorder_point | integer | Trigger threshold for reorders | HAVING filter for reorder query |
| products | discontinued | boolean | Lifecycle flag | WHERE filter for active products |
| warehouses | warehouse_id | integer PK | Unique warehouse identifier | JOIN key |
| warehouses | capacity | integer | Max storage units | Upper bound check |
| inventory | quantity_on_hand | integer | Current stock at this warehouse | SUM for total stock |
| inventory | last_updated | timestamp | When stock was last counted | Recency check for stale data |
| stock_movements | movement_type | enum | Type of stock change | Filter for inbound/outbound analysis |
| stock_movements | quantity | signed integer | Change in stock (signed) | SUM for net change |
| stock_movements | movement_date | timestamp | When movement occurred | WHERE for time-range queries |

## Business Logic

**Available stock**: `quantity_on_hand > 0` from inventory table.
Negative stock is theoretically impossible but may appear due to data-entry lag (treat as 0 for valuation).

**Products needing reorder**: `SUM(quantity_on_hand) <= reorder_point` across ALL warehouses for that product.
Rationale: total stock across the network, not per-warehouse stock.

**Active products only**: Exclude `discontinued = true` unless explicitly analyzing discontinued items.
Rationale: discontinued products don't trigger reorders even if below reorder_point.

**Stock valuation**: `SUM(quantity_on_hand * unit_cost)` per product (or per warehouse).

**Movement type semantics**:
- `inbound`: positive quantity (stock arriving)
- `outbound`: negative quantity (stock leaving)
- `transfer`: neutral (move between warehouses — net zero across network)
- `adjustment`: physical count correction (positive or negative)

## Few-shot Examples

### Example 1: Products below reorder point (network-wide)

```sql
SELECT
  p.product_id,
  p.product_name,
  p.reorder_point,
  SUM(i.quantity_on_hand) AS total_stock,
  p.unit_cost,
  (p.reorder_point - SUM(i.quantity_on_hand)) AS units_to_reorder
FROM products p
JOIN inventory i ON p.product_id = i.product_id
WHERE p.discontinued = false
GROUP BY p.product_id, p.product_name, p.reorder_point, p.unit_cost
HAVING SUM(i.quantity_on_hand) <= p.reorder_point
ORDER BY units_to_reorder DESC;
```

### Example 2: Stock value per warehouse

```sql
SELECT w.warehouse_name, SUM(i.quantity_on_hand * p.unit_cost) AS stock_value
FROM inventory i
JOIN products p ON i.product_id = p.product_id
JOIN warehouses w ON i.warehouse_id = w.warehouse_id
WHERE p.discontinued = false
GROUP BY w.warehouse_name
ORDER BY stock_value DESC;
```

### Example 3: Stock movements over the last 30 days

```sql
SELECT DATE(movement_date) AS day, SUM(quantity) AS net_change
FROM stock_movements
WHERE movement_date >= CURRENT_DATE - INTERVAL '30 days'
  AND movement_type IN ('inbound', 'outbound')
GROUP BY DATE(movement_date)
ORDER BY day;
```

## Chart Generation

When the user asks for a chart or visualization, use the `generate_chart` tool.

**How to use generate_chart:**
1. First, write a SQL query that returns **2 columns**: label (1st column) and value (2nd column)
2. Call `generate_chart(sql, chart_type, title)` with the query
3. Example: After finding products needing reorder, call `generate_chart` with `SELECT product_name, units_to_reorder FROM ...` and `chart_type="horizontal_bar"`

**Recommended chart types by scenario:**
- **bar**: Comparing stock levels across products or warehouses
- **horizontal_bar**: Many products or long product names — better readability
- **pie**: Showing stock distribution by warehouse or category
- **line**: Showing stock movement trends over time

## Edge Cases & Pitfalls

### 1. Per-warehouse vs network-wide stock
❌ `WHERE i.quantity_on_hand <= p.reorder_point` (per-warehouse)
✅ `HAVING SUM(i.quantity_on_hand) <= p.reorder_point` (network-wide)

### 2. Including discontinued products in reorder list
❌ Generates reorders for products we no longer sell
✅ `WHERE p.discontinued = false`

### 3. Counting transfers as stock changes
❌ `SUM(quantity) FROM stock_movements` — transfers net to zero but inflate the count
✅ Filter `WHERE movement_type IN ('inbound', 'outbound')` for net change
✅ Filter `WHERE movement_type = 'inbound'` for arrivals only

### 4. Negative quantity_on_hand
Theoretically impossible; caused by data-entry lag (outbound before inbound recorded).
✅ Treat as 0 for valuation: `GREATEST(quantity_on_hand, 0)`
❌ Multiplying by unit_cost → negative stock value

### 5. Stock at capacity warehouses
If `SUM(i.quantity_on_hand) > w.capacity`, that's an error state.
✅ Flag: `HAVING SUM(i.quantity_on_hand) > w.capacity` returns overflow warehouses
❌ Silently including in "available stock" counts

### 6. NULL unit_cost
Some legacy products may have `unit_cost = NULL`.
✅ Exclude from valuation: `WHERE unit_cost IS NOT NULL`
❌ Including NULLs → SUM returns NULL for the whole row

### 7. Stock movement date in the future
Data entry errors can put `movement_date > CURRENT_DATE`.
✅ Filter `WHERE movement_date <= CURRENT_DATE`
❌ Future movements distort trend analysis