---
name: market_wizard
description: 市场数据清洗技能。将市场部导出的脏数据(market, qty, prod_cat, price_per_unit, rebate)规范化为 finance_pro 期望的标准列名(Region, Quantity, Product_Category, Unit_Price, Discount)。
---

## Data Source

**输入**:市场部导出的 CSV,典型样例(`modern_marketing.csv`):
```
tx_id,market,prod_cat,qty,price_per_unit,rebate
MKT_999,US,Software,20,$500.00,100.0
MKT_1000,EMEA,Hardware,2,"$1,250.00",10.0
MKT_1001,LATAM,Services,1,"$2,100.00",50.0
```

**输出**:符合 §Column Metadata 的 DataFrame,保存到 `enterprise_data/cleaned_<input_name>.csv`。

## Column Metadata

### Canonical Schema (输出)

| Canonical Name | Data Type | Semantic | Usage |
|---|---|---|---|
| transaction_id | string (unique) | 交易编号 | 索引、识别唯一交易 |
| region | enum (US / EMEA / APAC / LATAM) | 销售地区 | 决定下游 tax_rate |
| product_category | enum (Software / Hardware / Services) | 产品类别 | 用于产品组合聚合 |
| quantity | int ≥ 0 | 销售数量 | 收入公式乘数 |
| unit_price | float > 0 | 单价,折扣前 | 收入公式乘数 |
| discount | float ≥ 0 | **绝对**折扣金额(美元) | 从总收入中减去 |

### Aliases (输入 → 输出)

| Input (脏) | Output (干净) | 源样例 |
|---|---|---|
| tx_id | transaction_id | `MKT_999` |
| market | region | `US` |
| prod_cat | product_category | `Software` |
| qty | quantity | `20` |
| price_per_unit | unit_price | `"$500.00"` (string!) |
| rebate | discount | `100.0` |

### 类型注意

- `price_per_unit` 是 **字符串**(带 `$` 和 `,`),必须 strip 后转 float。
- `rebate` 是 **绝对美元数**(不是百分比)。`rebate=100.0` 表示 $100 折扣。
- `qty` 在源文件可能是 string (`"20"`),需转 int。
- `region` 在不同文件中枚举值不同(US/EMEA/APAC vs US/EMEA/LATAM) — 保留原值,下游按值决定税率。

## Business Logic

### 1. 列名规范化
按 §Aliases 表做 1:1 重命名。不做模糊匹配(避免误改)。

### 2. 货币字段清洗
```python
df["unit_price"] = (
    df["unit_price"]
    .astype(str)
    .str.replace("$", "", regex=False)
    .str.replace(",", "", regex=False)
    .astype(float)
)
```

### 3. 数值字段类型转换
```python
df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
df["discount"] = pd.to_numeric(df["discount"], errors="coerce").fillna(0.0)
```

### 4. region 大小写规范化
```python
df["region"] = df["region"].str.upper().str.strip()
```

### 5. 文件命名
清洗后的文件保存为:
```
enterprise_data/cleaned_<original_filename>.csv
```

例: `modern_marketing.csv` → `cleaned_modern_marketing.csv`

### 6. 输出 schema 必须被 finance_pro 接受
- 列名严格匹配 §Canonical Schema
- 单位 / 类型严格匹配
- 没有额外列(下游 `finance_pro` 不会处理未知列)

## Few-shot Examples

### Example 1: 清洗 `modern_marketing.csv`

```python
import pandas as pd

ALIAS = {
    "tx_id": "transaction_id",
    "market": "region",
    "prod_cat": "product_category",
    "qty": "quantity",
    "price_per_unit": "unit_price",
    "rebate": "discount",
}

df = pd.read_csv("enterprise_data/modern_marketing.csv")
df = df.rename(columns=ALIAS)
df["unit_price"] = (
    df["unit_price"].astype(str)
    .str.replace("$", "", regex=False)
    .str.replace(",", "", regex=False)
    .astype(float)
)
df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
df["discount"] = pd.to_numeric(df["discount"], errors="coerce").fillna(0.0)
df["region"] = df["region"].str.upper().str.strip()
df.to_csv("enterprise_data/cleaned_modern_marketing.csv", index=False)
```

**Input row**: `MKT_999,US,Software,20,$500.00,100.0`
**Output row**: `transaction_id,region,product_category,quantity,unit_price,discount\nMKT_999,US,Software,20,500.0,100.0`

### Example 2: 清洗带引号的字符串(`"$1,250.00"`)

`pandas.read_csv` 默认处理带引号的字段(返回 `"$1,250.00"` 字符串)。
✅ 用 `.str.replace` 多次清理。
❌ 用 `pd.eval` 或 `locale.atof`(对小数据集 OK,但大文件慢)。

### Example 3: 处理缺失 discount

```python
# 输入: row 的 discount 列为空 → pd.to_numeric 后是 NaN
df["discount"] = pd.to_numeric(df["discount"], errors="coerce").fillna(0.0)
# 缺失 → 0.0(假定无折扣,而不是 NaN)
```

## Edge Cases & Pitfalls

### 1. price_per_unit 已经是 float 的情况
某些 CSV 已经清洗过,`unit_price` 是 `500.0` 而非 `"$500.00"`。
✅ `.astype(str)` 先转字符串,再 strip — 对两种情况都安全。
❌ 直接 `.str.replace("$", "")` 在 float 列上会 AttributeError。

### 2. region 大小写不一致
`US` vs `us` vs ` Us `。
✅ 强制 `.str.upper().str.strip()` 规范化。
❌ 保留原值 → 下游 `TAX_RATES` map 会失败。

### 3. 缺失列
若输入缺少 `rebate` 列(没有折扣):
✅ 先创建零列:`df["discount"] = 0.0`,再继续。
❌ 直接 `df["discount"] = ...` 当列不存在 → KeyError。

### 4. 列顺序不一致
不同文件列顺序不同(Region 在 Quantity 前 vs 后)。
✅ 用 `rename(columns=...)`,不依赖位置。
❌ 用位置索引 `df.columns = [...]` — 顺序错了就崩。

### 5. 文件读取失败
`unicode_decode_error`(BOM / UTF-16 / Latin-1 编码):
✅ 尝试 `encoding="utf-8-sig"`(去 BOM)。
❌ 不指定 encoding 直接 `read_csv`(默认 utf-8 失败时抛 UnicodeDecodeError)。

### 6. 输出 schema 校验
清洗后必须满足 finance_pro 的输入要求:
- 6 列:`transaction_id, region, product_category, quantity, unit_price, discount`
- 类型:str, str, str, int, float, float
- region 大写
- 数量/价格为非负

清洗结束后用一个 assertion 校验:
```python
expected = ["transaction_id", "region", "product_category", "quantity", "unit_price", "discount"]
assert list(df.columns) == expected, f"Schema mismatch: got {list(df.columns)}"
```