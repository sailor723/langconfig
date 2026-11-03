#### TPC-H — 语义层（给 SQL 图的 SEMANTICS）

> 只放 DDL 看不出来的东西。指标以本库 `unit_registry` 为准（A 段），数字由 `check_semantics.py` 核对。

### 表与 join

`region` 5 · `nation` 25 · `customer` 15,000 · `supplier` 1,000 · `part` 20,000 ·
`partsupp` 80,000 · `orders` 150,000 · `lineitem` 600,572（SF≈0.1，每单 4.004 行）

```
lineitem.l_orderkey→orders   orders.o_custkey→customer   customer.c_nationkey→nation
nation.n_regionkey→region    lineitem.(l_partkey,l_suppkey)→partsupp(ps_partkey,ps_suppkey)
```

### A. 已注册指标（`unit_registry`）

| id | 指标 | 定义 | 粒度 | 单位 | 方向 | 实测 |
|---|---|---|---|---|---|---|
| A1 | `order_line.revenue` | `SUM(l_extendedprice*(1-l_discount))` | lineitem | money | 高 | 20,535,072,231.4150 |
| A2 | `order_line.gross_revenue` | `SUM(l_extendedprice)` | lineitem | money | 高 | 21,615,929,280.24 |
| A3 | `order_line.total_discount` | `SUM(l_extendedprice*l_discount)` | lineitem | money | 低 | 1,080,857,048.83 |
| A4 | `order_line.average_line_value` | `A1 / COUNT(*)` | lineitem | money/行 | 高 | 34,192.52 |
| A5 | `order_line.supply_cost` | `SUM(ps_supplycost*l_quantity)`（规则 4） | lineitem | money | 低 | 7,657,917,294.19 |
| A6 | `order_line.contribution_margin` | `A1 - A5` | lineitem | money | 高 | 12,877,154,937.23 |
| A7 | `order_line.contribution_margin_pct` | `100*(A1-A5)/A1` | lineitem | **percent** | 高 | 62.71 |
| A8 | `order_line.weighted_average_discount` | `A3 / A2`（保持 **ratio**） | lineitem | ratio | 低 | 0.050003 |
| A9 | `sales_order.average_order_value` | 按 `o_orderkey` 汇总 A1 再 `AVG` | orders | money/单 | 高 | 136,900.48 |

### B. 运营比率（本文件定义，`unit_registry` 无规则号）

| id | 指标 | 定义 | 单位 | 方向 | 实测 |
|---|---|---|---|---|---|
| B1 | 延迟交付率 | `COUNT(l_shipdate>l_commitdate)/COUNT(*)` | percent | 低 | 50.41 |
| B2 | 退货率 | `COUNT(l_returnflag='R')/COUNT(*)` | percent | 低 | 24.69 |
| B3 | 高余额客户数 | `COUNT(*) WHERE c_acctbal>=5000` | count | 高 | 6,733 |
| B4 | 负余额供应商数 | `COUNT(*) WHERE s_acctbal<0` | count | 低 | 88 |

### 口径规则

1. **"总收入"有三个，差约 5%**：A2 21,615,929,280.24 · A1 20,535,072,231.42 ·
   `SUM(o_totalprice)` 21,356,596,030.63（含税、订单级四舍五入）。报数必须报名。
2. **ratio ≠ percent**：`l_discount`/`l_tax`/A8 是 ratio（0.04=4%）；A7 已乘 100。
   比率不能用 `AVG`（`AVG(l_discount)` 未加权），用 A8。
3. **延迟交付 50.41%，不是"表现良好"**：生成器不保证 `ship<=commit`（302,748 延迟 /
   5,052 同日 / 292,772 提前，平均 +1.0 天），准时率 ≈49.59%。报交付率先给定义。
4. **成本只在 `partsupp`**：A5/A6/A7 必须 `ON l_partkey AND l_suppkey`（两列）；
   只连 `l_partkey` 会把行数放大 80 倍。
5. **封闭历史库 1992-01-01→1998-08-02**：无"今年"锚点，`CURRENT_DATE` 过滤得 0 行；
   按年用 `EXTRACT(year FROM o_orderdate)` 并说明止于 1998。
6. **五个大区各约 20%（20.32/20.07/19.99/19.88/19.75）**：差距 <0.6pp 是合成数据的均匀性，
   不是经营洞察。
7. **订单级金额不能和 `lineitem` join 后再 `SUM`——扇出 4 倍**：

   | id | 断言 | 实测 |
   |---|---|---|
   | R1 | 1998 订单头总额，`FROM orders` 单独聚合 | 1,933,789,650 |
   | R2 | 同一数字，`lineitem⋈orders` 后聚合 | 9,703,462,214 |

   订单级指标只在 `orders` 层聚合；要加行级筛选，先子查询去重订单键。
8. **没有费用科目 → 算不出净利润/ROE/现金流**：能算 A1-A9、B1-B4；被问到说明缺口，
   给毛利 A6/A7，不要拿 `o_totalprice` 冒充利润。

### 回答规则

- 金额报名；比率说明 ratio/percent 与是否加权；交付/退货类给定义；时间用 `o_orderdate`。
- 库里没有的字段不编；`order_line`/`sales_order` 是逻辑实体（无物理表），按表名 join 会失败。
