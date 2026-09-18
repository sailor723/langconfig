---
name: finance_pro
description: 财务核算技能。处理各地区(EMEA, US, APAC)的专项税率逻辑,计算净收入,识别表现不佳(UNDER_PERFORMING)的警告。
---

## Data Source

输入:由 `market_wizard` 清洗后的 CSV,或任意符合 §Column Metadata 的 DataFrame。

样例行(清洗后):
```
TransactionID | Region | Product_Category | Quantity | Unit_Price | Discount
TXN_001       | US     | Software         | 10       | 500.0      | 50.0
```

## Column Metadata

### Input contract (canonical schema)

This skill expects a DataFrame already conforming to:

| Canonical Name | Data Type | Semantic | Usage |
|---|---|---|---|
| transaction_id | string (unique) | 交易编号 | 标识唯一交易,可作索引 |
| region | enum (US / EMEA / APAC / LATAM) | 销售地区,决定税率 | GROUP BY 用于按地区聚合 |
| product_category | enum (Software / Hardware / Services) | 产品类别 | GROUP BY 用于产品组合分析 |
| quantity | int ≥ 0 | 销售数量(不是收入) | 收入公式的乘数 |
| unit_price | float > 0 | 单价,折扣前 | 收入公式的乘数 |
| discount | float ≥ 0 | **绝对**折扣金额(不是百分比) | 从总收入中减去 |

> 💡 This schema is typically produced by the `market_wizard` skill, but this
> skill works on ANY DataFrame matching the schema — it doesn't require market_wizard.

### Expected dirty aliases (for context only)

If the input is NOT yet cleaned, common dirty column names map as:

| Dirty name | Canonical name |
|---|---|
| tx_id, TransactionID | transaction_id |
| market, Region | region |
| prod_cat, Product_Category | product_category |
| qty, Quantity | quantity |
| price_per_unit, Unit_Price | unit_price |
| rebate, Discount | discount |

### 类型注意

- 清洗前 `unit_price` 可能是字符串(带 `$` 和 `,`):`"$1,250.00"` → 必须 strip 后转 float。
- 清洗前 `discount`/`rebate` 单位是美元(绝对值),不是百分比。

## Business Logic

### 1. 总收入 (Gross Revenue)
```
gross_revenue = quantity × unit_price
```

### 2. 净收入 (Net Revenue,税前)
```
net_revenue = gross_revenue - discount
```
> **重要**:discount 是绝对金额,直接相减。**不要**把 discount 当作百分比处理。

### 3. 区域税率

| Region | Tax Rate |
|---|---|
| US | 8% |
| EMEA | 15% |
| APAC | 12% |
| LATAM | **0%** (待定 — 报告中需 ⚠️ 标记) |

### 4. 应纳税额 & 税后净收入
```
tax = net_revenue × tax_rate
net_after_tax = net_revenue × tax
= net_revenue × (1 - tax_rate)
```

### 5. UNDER_PERFORMING 判定
若一个 region 的 **net_after_tax 总和** < **500**,必须:
- 在报告顶部标 `⚠️ UNDER_PERFORMING`
- 在分析中给出原因假设

### 6. 数据流(执行顺序)
1. `market_wizard` 先清洗原始 CSV(列名规范化、`$/,` 剥离)
2. 本技能读取清洗后的数据
3. 使用 `python_analyst` 执行计算
4. 使用 `generate_report` 输出柱状图 + 饼图
5. 用中文输出完整洞察

## Few-shot Examples

### Example 1: 按地区计算净收入

```python
df["net_revenue"] = df["quantity"] * df["unit_price"] - df["discount"]
df["tax_rate"] = df["region"].map(TAX_RATES).fillna(0)
df["net_after_tax"] = df["net_revenue"] * (1 - df["tax_rate"])
by_region = df.groupby("region")["net_after_tax"].sum().sort_values(ascending=False)
```

Expected output(modern_marketing.csv 清洗后):
```
region
US      9108.0
LATAM   2050.0
EMEA    2030.0
```

### Example 2: 识别 UNDER_PERFORMING

```python
THRESHOLD = 500
under = by_region[by_region < THRESHOLD].index.tolist()
# modern_marketing.csv → [] (没有 region 触发)
```

### Example 3: 生成柱状图 + 饼图

```python
import matplotlib.pyplot as plt
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
by_region.plot(kind="bar", ax=ax1, title="净收入按地区")
df.groupby("product_category")["net_revenue"].sum().plot(kind="pie", ax=ax2, autopct="%1.1f%%")
plt.savefig("reports/finance_summary.png", dpi=150, bbox_inches="tight")
```

## Edge Cases & Pitfalls

### 1. 字符串类型的 unit_price
❌ `df["unit_price"].sum()` 当列是 `"$1,250.00"` → ERROR 或错误结果
✅ 先清洗:`df["unit_price"].str.replace("$","").str.replace(",","").astype(float)`

### 2. discount 当作百分比
❌ `quantity × unit_price × (1 - discount/100)` → 结果错误(扩大 100 倍)
✅ `quantity × unit_price - discount`(discount 是美元金额)

### 3. region 不在已知集合
如果出现 `LATAM`(或任何新地区):
- 默认 `tax_rate = 0`(`fillna(0)`)
- 在报告中 ⚠️ 标记 "未定义税率,假定 0%,请业务确认"

### 4. 缺失 Quantity / Unit_Price
若某行 `quantity == 0` 或 `unit_price == 0`:net_revenue 为 0,不计入 under_performing 检查(避免除零误判)。

### 5. 负 quantity
视为退货/退款:
- 应从"已完成销售"汇总中排除
- revenue 取负值
- ✅ `df = df[df["quantity"] > 0]`(用于正向分析)