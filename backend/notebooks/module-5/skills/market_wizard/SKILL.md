---
name: market_wizard
description: 通用 CSV 数据清洗技能。基于 YAML 规则将脏数据规范化为标准 schema,供下游分析技能使用。引擎通用、内容无关,规则写在 rules.yaml。
---

# Market Wizard — Generic CSV Cleaning

This skill cleans messy CSV files into a canonical schema using a **content-free
wizard engine** (`backend/core/data_prep/wizard.py`) driven by a **YAML rules file**.

```
┌──────────────────────────────────────────────────────────────┐
│  YAML rules (content)   →   Generic engine (no content)     │
│  - which aliases         -   reads spec, applies rules      │
│  - which transforms      -   validates output               │
│  - which schema          -   writes cleaned CSV             │
└──────────────────────────────────────────────────────────────┘
```

## Data Source

**Input**: Any CSV with column names matching the aliases in `rules.yaml`.

**Output**: A cleaned CSV conforming to the schema specified in `rules.yaml`
(currently `CleanedSalesRow` from `backend/schemas/sales.py`).

**Files**:
- Rules: `skills/market_wizard/rules.yaml` (THIS skill's content)
- Engine: `core/data_prep/wizard.py` (generic, reusable for other skills)
- Schema: `schemas/sales.py` (shared with `finance_pro`)

## Column Metadata

The **canonical output schema** is defined in code (Pydantic), not in this doc.

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

> 💡 To change the schema: edit `backend/schemas/sales.py`. This affects
> BOTH this skill (output) and `finance_pro` (input) — single source of truth.

## Data Cleaning Rules

The actual transformation rules live in `rules.yaml`:

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

### Supported transforms (whitelist)

| Transform | Example | Effect |
|---|---|---|
| `upper` | `"us"` | `"US"` |
| `lower` | `"US"` | `"us"` |
| `strip` | `" US "` | `"US"` |
| `upper.strip` | `" us "` | `"US"` |
| `strip_dollar_comma` | `"$1,250.00"` | `1250.0` |
| `strip_percent` | `"15%"` | `15.0` |
| `to_int` | `"20"` | `20` |
| `to_float` | `"500"` | `500.0` |

### Adding a new data source

1. Add a new `rules.yaml` for that source (or extend existing one)
2. Define the schema in `schemas/` (or reuse existing)
3. Run: `python -m core.data_prep.wizard path/to/rules.yaml`

No code changes needed in the wizard itself.

## Few-shot Examples

### Example 1: Run the wizard

```bash
cd backend
python -m core.data_prep.wizard \
    notebooks/module-5/skills/market_wizard/rules.yaml \
    notebooks/module-5/enterprise_data/modern_marketing.csv
```

Output:
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

### Example 2: Use the wizard programmatically

```python
from pathlib import Path
from core.data_prep import run

result = run(
    spec_path=Path("skills/market_wizard/rules.yaml"),
    input_path=Path("enterprise_data/modern_marketing.csv"),
)
assert result["status"] == "ok"
```

### Example 3: Validate output against schema

```python
import pandas as pd
from schemas import CleanedSalesRow

df = pd.read_csv("enterprise_data/cleaned_modern_marketing.csv")
for _, row in df.iterrows():
    CleanedSalesRow.model_validate(row.to_dict())  # raises on invalid
```

## Edge Cases & Pitfalls

### 1. Schema mismatch
❌ Adding a column to rules.yaml that's NOT in `CleanedSalesRow`
✅ Always match the schema defined in `backend/schemas/sales.py`

### 2. Missing source column
❌ Wizard silently skips the rule (just logs warning)
✅ Use the `default:` field in YAML for required-but-missing columns
✅ Or fix the input CSV to have the expected column

### 3. Invalid enum values
❌ `region: "USA"` (not in Literal["US", "EMEA", "APAC", "LATAM"])
✅ Pydantic validation catches this; wizard reports `validation_failed`

### 4. Negative quantity or price
❌ `-5` quantity or `0.0` price passes cleaning
✅ Caught by `Field(ge=0)` / `Field(gt=0)` in CleanedSalesRow

### 5. String concatenation instead of enum
❌ `region: "US,EMEA"` (multiple values in one cell)
✅ Each row should have ONE region; split rows if needed

### 6. Currency in discount
❌ `discount: "$50"` (string with $)
✅ Use `transform: strip_dollar_comma` in rules.yaml

### 7. Empty CSV
❌ Crashes or unclear error
✅ Wizard returns `rows_in: 0, rows_valid: 0` (no crash)

### 8. Special characters in column names
❌ `"Unit Price"` with space — YAML string literal
✅ Quote it: `from: ["Unit Price"]` or `from: 'Unit Price'`