---
name: "market-wizard（通用 CSV 清洗向导）"
lang: zh
translated: machine
source: backend/skills/en-originals/market-wizard/SKILL.md
description: 通用 CSV 数据清洗技能。基于 YAML 规则把脏数据规范化为标准 schema，供下游分析技能使用。引擎通用、内容无关，规则写在 rules.yaml。
---

# Market Wizard（通用 CSV 清洗）

本技能用一个**内容无关的向导引擎**（`backend/core/data_prep/wizard.py`），由一份 **YAML 规则文件**驱动，把杂乱的 CSV 文件清洗成规范 schema。

```
┌──────────────────────────────────────────────────────────────┐
│  YAML rules (content)   →   Generic engine (no content)     │
│  - which aliases         -   reads spec, applies rules      │
│  - which transforms      -   validates output               │
│  - which schema          -   writes cleaned CSV             │
└──────────────────────────────────────────────────────────────┘
```

## Data Source（数据来源）

**输入**：任意 CSV，其列名能对上 `rules.yaml` 中的别名。

**输出**：一份清洗后的 CSV，符合 `rules.yaml` 指定的 schema
（当前是 `backend/schemas/sales.py` 里的 `CleanedSalesRow`）。

**文件**：
- 规则：`skills/market-wizard/rules.yaml`（本技能的内容）
- 引擎：`core/data_prep/wizard.py`（通用，其他技能可复用）
- Schema：`schemas/sales.py`（与 `finance_pro` 共用）

## Column Metadata（列元数据）

**规范输出 schema** 定义在代码里（Pydantic），不在这份文档里。

```python
# backend/schemas/sales.py
class CleanedSalesRow(BaseModel):
    transaction_id: str
    region: Literal["US", "EMEA", "APAC", "LATAM"]
    product_category: Literal["Software", "Hardware", "Services"]
    quantity: int = Field(ge=0)
    unit_price: float = Field(gt=0)
    discount: float = Field(ge=0, default=0.0)
```

> 💡 要改 schema：编辑 `backend/schemas/sales.py`。这会同时影响
> 本技能（输出）和 `finance_pro`（输入）——唯一来源。

## Data Cleaning Rules（清洗规则）

实际的转换规则位于 `rules.yaml` 里：

```yaml
schema: CleanedSalesRow
source: enterprise_data/modern_marketing.csv
target: enterprise_data/cleaned_modern_marketing.csv

mapping:
  - from: [tx_id, TransactionID]
    to: transaction_id
    type: str
  - from: [market, Region]
    to: region
    type: str
    transform: upper.strip
  - from: [price_per_unit, Unit_Price, "Unit Price"]
    to: unit_price
    type: float
    transform: strip_dollar_comma
  - from: [rebate, Discount]
    to: discount
    type: float
    default: 0.0
```

### 支持的变换（白名单）

| 变换 | 示例 | 效果 |
|---|---|---|
| `upper` | `"us"` | `"US"` |
| `lower` | `"US"` | `"us"` |
| `strip` | `" US "` | `"US"` |
| `upper.strip` | `" us "` | `"US"` |
| `strip_dollar_comma` | `"$1,250.00"` | `1250.0` |
| `strip_percent` | `"15%"` | `15.0` |
| `to_int` | `"20"` | `20` |
| `to_float` | `"500"` | `500.0` |

### 新增一个数据源

1. 为该数据源新增一份 `rules.yaml`（或扩展现有那份）
2. 在 `schemas/` 里定义 schema（或复用已有的）
3. 运行：`python -m core.data_prep.wizard path/to/rules.yaml`

向导本身不需要改任何代码。

## Few-shot Examples（少样本示例）

### 示例 1：运行向导

```bash
cd backend
python -m core.data_prep.wizard \
    notebooks/module-5/skills/market_wizard/rules.yaml \
    notebooks/module-5/enterprise_data/modern_marketing.csv
```

输出：
```json
{
  "status": "ok",
  "rows_in": 3,
  "rows_valid": 3,
  "warnings": [],
  "errors": [],
  "schema": "CleanedSalesRow"
}
```

### 示例 2：在代码里调用向导

```python
from pathlib import Path
from core.data_prep import run

result = run(
    spec_path=Path("skills/market-wizard/rules.yaml"),
    input_path=Path("enterprise_data/modern_marketing.csv"),
)
assert result["status"] == "ok"
```

### 示例 3：用 schema 校验输出

```python
import pandas as pd
from schemas import CleanedSalesRow

df = pd.read_csv("enterprise_data/cleaned_modern_marketing.csv")
for _, row in df.iterrows():
    CleanedSalesRow.model_validate(row.to_dict())  # raises on invalid
```

## Edge Cases & Pitfalls（边界情况与陷阱）

### 1. schema 不匹配
❌ 往 rules.yaml 里加一个 `CleanedSalesRow` 里没有的列
✅ 永远对齐 `backend/schemas/sales.py` 里定义的 schema

### 2. 源列缺失
❌ 向导静默跳过该规则（只记一条警告）
✅ 对必需但可能缺失的列，用 YAML 的 `default:` 字段
✅ 或者修好输入 CSV，让它带上预期的列

### 3. 枚举值非法
❌ `region: "USA"`（不在 Literal["US", "EMEA", "APAC", "LATAM"] 里）
✅ Pydantic 校验会抓住它；向导报告 `validation_failed`

### 4. 数量或单价为负
❌ 数量 `-5` 或单价 `0.0` 通过了清洗
✅ 由 `CleanedSalesRow` 里的 `Field(ge=0)` / `Field(gt=0)` 抓住

### 5. 用拼接字符串代替枚举
❌ `region: "US,EMEA"`（一个单元格里塞多个值）
✅ 每行只应有一个地区；需要时把行拆开

### 6. 折扣里带货币符号
❌ `discount: "$50"`（带有 $ 的字符串）
✅ 在 rules.yaml 里用 `transform: strip_dollar_comma`

### 7. 空 CSV
❌ 崩溃，或报一个看不懂的错
✅ 向导返回 `rows_in: 0, rows_valid: 0`（不崩溃）

### 8. 列名里有特殊字符
❌ `"Unit Price"` 带空格——这是 YAML 字符串字面量
✅ 加引号：`from: ["Unit Price"]` 或 `from: 'Unit Price'`
