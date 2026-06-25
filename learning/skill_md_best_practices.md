# SKILL.md Best Practices — Authoring Guide

> A reference for writing high-quality `SKILL.md` files. Captures lessons learned
> from analyzing `sales_analytics` (the gold standard), `finance_pro`, `market_wizard`,
> and our discussion in Phase 6.

## Why This Document Exists

Skills are the unit of modular capability for our DeepAgent agents. A well-written
SKILL.md makes the LLM:
- Understand the data shape without trial-and-error
- Apply domain rules correctly (no hallucinated business logic)
- Produce reproducible, auditable outputs

A poorly-written SKILL.md makes the LLM:
- Guess column names and types
- Invent business rules that don't match reality
- Produce different results on the same data

---

## The 5-Section Template

```
┌────────────────────────────────────────────────────────────────┐
│  1. Data Source        — Where's the data, what does it look   │
│  2. Column Metadata    — Name, type, semantic, usage, aliases   │
│  3. Business Logic     — Formulas, thresholds, domain rules    │
│  4. Few-shot Examples  — Concrete input→output, runnable code   │
│  5. Edge Cases         — What goes wrong, how to avoid         │
└────────────────────────────────────────────────────────────────┘
```

This structure was inspired by `sales_analytics/SKILL.md` (the gold standard in
our codebase) and refined based on the **actual messiness** we found in our
sample CSV data (`modern_marketing.csv` vs `standard_sales.csv`).

---

## Section 1: Data Source

### Purpose
Tell the agent **where the data lives** and **what it looks like in raw form**.

### What to include
- Path(s) to the data files
- 2-3 sample rows from each file (showing actual values, not placeholders)
- Note any **naming convention differences** between files

### Example

```markdown
## Data Source

**Primary** (clean, canonical): `enterprise_data/standard_sales.csv`
**Messy variant** (same business data, dirty columns): `enterprise_data/modern_marketing.csv`

Sample row from `standard_sales.csv`:
```
TransactionID | Date       | Region | Product_Category | Quantity | Unit_Price | Discount
TXN_001       | 2023-12-01 | US     | Software         | 10       | 500.0      | 50.0
```

Sample row from `modern_marketing.csv`:
```
tx_id    | market | prod_cat | qty | price_per_unit | rebate
MKT_999  | US     | Software | 20  | $500.00        | 100.0
```

**Observation**: Both files contain the same business data, but with different
column names AND different value formats (currency strings vs floats).
```

### Length: 5-15 lines + sample rows

---

## Section 2: Column Metadata

### Purpose
Define **every column** the agent will encounter. Each column gets 4 fields:
- **Canonical name** (what to use in code)
- **Data type** (with quirks)
- **Semantic** (what it MEANS, not just what it stores)
- **Usage** (how to use it in queries — filter? aggregate? multiply?)

### Format: Table per schema + alias map

```markdown
## Column Metadata

### Canonical Schema (after cleaning)

| Name | Data Type | Semantic | Usage |
|---|---|---|---|
| transaction_id | string (unique) | Identifies one sale | GROUP BY for per-tx analysis |
| date | date (YYYY-MM-DD) | When the sale occurred | WHERE for time-range filters |
| region | enum (US / EMEA / APAC / LATAM) | Geographic market — drives tax rate | GROUP BY for regional aggregations |
| product_category | enum (Software / Hardware / Services) | Type of product sold | GROUP BY for product mix |
| quantity | int ≥ 0 | Units sold (NOT revenue!) | Multiplier in revenue formula |
| unit_price | float > 0 | Price per unit, BEFORE discount | Multiplier in revenue formula |
| discount | float ≥ 0 | Absolute discount amount (NOT percentage) | Subtracted from gross revenue |

### Aliases (for dirty data)

| Dirty name | Source | Canonical name |
|---|---|---|
| tx_id, TransactionID | modern_marketing.csv, standard_sales.csv | transaction_id |
| market, Region | modern_marketing.csv, standard_sales.csv | region |
| prod_cat, Product_Category | modern_marketing.csv, standard_sales.csv | product_category |
| qty, Quantity | modern_marketing.csv, standard_sales.csv | quantity |
| price_per_unit, Unit_Price | modern_marketing.csv, standard_sales.csv | unit_price |
| rebate, Discount | modern_marketing.csv, standard_sales.csv | discount |

### Type Quirks

- `price_per_unit` in `modern_marketing.csv` is a **STRING with `$` and `,`**
  - Example: `"$1,250.00"` must be stripped before arithmetic
- `region` enum differs across files:
  - `standard_sales.csv`: US / EMEA / APAC (3 regions)
  - `modern_marketing.csv`: US / EMEA / LATAM (3 regions, **no APAC!**)
```

### Why this format
- **Type** column catches bugs (the `$1,250.00` string issue)
- **Semantic** column prevents wrong assumptions (quantity ≠ revenue)
- **Usage** column guides the LLM on WHERE/WHAT/GROUP BY
- **Alias map** prevents the LLM from inventing column names

### Length: 1 table per schema + alias map + type quirks

---

## Section 3: Business Logic

### 3. Business Logic
Capture **institutional knowledge** that doesn't exist anywhere else. These are
the rules an experienced analyst knows but a new hire wouldn't.

### What to include
- Formulas (precise, with operators)
- Constants (tax rates, thresholds)
- Domain vocabulary ("active customer", "high-value order")
- **Exceptions and flags** (e.g., LATAM has no tax rate defined)

### Format: Numbered rules with precise formulas

### ⚠️ Special case: Data-Preparation Skills

Some skills **do NOT answer business questions directly** — they prepare data
for downstream skills. Examples: `market_wizard` (cleans CSV), `data-loader`
(loads DB), `feature-extractor`.

**Recommended approach** (loose coupling):
- Remove the "Business Context" section entirely from data-prep skills
- Add a single hint to the **frontmatter description**:
  ```yaml
  description: Cleans messy market CSVs to canonical schema, for downstream business analysis.
  ```
- Section 3 of the SKILL.md is purely **Data Cleaning Rules** (no business questions)

**Why loose coupling**:
- market_wizard should NOT know what business questions its output enables
- It should ONLY know how to clean data correctly
- The downstream analysis skill (e.g., finance_pro) describes its own input contract
- This keeps each skill independently maintainable

**Example**: market_wizard has Section 3 = "Data Cleaning Rules" only.
              finance_pro has Section 3 = "Business Logic" only.
              Each describes ITS OWN concerns, not the other's.

### Example Business Logic section (analysis skill)

### 1. Gross Revenue per Transaction
**Formula**: `gross_revenue = quantity × unit_price`

### 2. Net Revenue per Transaction (after discount, before tax)
**Formula**: `net_revenue = quantity × unit_price - discount`
**Important**: Apply discount as an absolute amount, NOT a percentage.

### 3. Regional Tax Rates

| Region | Tax Rate |
|---|---|
| US | 8% |
| EMEA | 15% |
| APAC | 12% |
| LATAM | **0%** (pending rate definition — flag in reports) |

### 4. Tax Calculation
- `tax = net_revenue × tax_rate`
- `net_after_tax = net_revenue × (1 - tax_rate)`

### 5. Under-Performing Region Rule
A region is **UNDER_PERFORMING** if its total `net_after_tax` < $500.
Triggers a manual review and adds ⚠️ to the report header.

### 6. Reproducible Time Window
"Current quarter" = last 90 days from `max(date)` in dataset, NOT today's date.
This makes results reproducible on historical data.
```

### What to AVOID in this section
- ❌ Vague descriptions ("Revenue is calculated based on sales")
- ❌ Missing exceptions ("All regions have a tax rate")
- ❌ Hidden thresholds ("Some orders are high-value")

### Length: 5-10 numbered rules

---

## Section 4: Few-shot Examples

### Purpose
Show the LLM **exactly what the right answer looks like** for common scenarios.
Examples are 10× more effective than descriptions.

### What to include
- 3-5 representative use cases (cleaning, analysis, edge case handling)
- For each: input → expected output + runnable code

### Format: Example N: Title + code block + expected output

```markdown
## Few-shot Examples

### Example 1: Clean messy CSV row

**Input** (modern_marketing.csv):
```
MKT_999,US,Software,20,$500.00,100.0
```

**Output** (canonical row):
```
TXN_MKT_999,2024-01-01,US,Software,20,500.0,100.0
```

**Steps**:
1. Rename columns: tx_id→transaction_id, market→region, etc.
2. Strip `$` and `,` from unit_price: `"$500.00"` → `500.0`
3. Add `date` if missing (use file mtime or ask user)

### Example 2: Revenue by Region

```python
df["net_revenue"] = df["quantity"] * df["unit_price"] - df["discount"]
df["tax_rate"] = df["region"].map(TAX_RATES).fillna(0)
df["net_after_tax"] = df["net_revenue"] * (1 - df["tax_rate"])
by_region = df.groupby("region")["net_after_tax"].sum().sort_values(ascending=False)
```

**Expected output** (on modern_marketing.csv):
```
region
US      9108.0
EMEA    2030.0
LATAM   2050.0
```

### Example 3: Identify Under-Performing Regions

```python
UNDER_PERFORMING_THRESHOLD = 500
by_region = df.groupby("region")["net_after_tax"].sum()
under = by_region[by_region < UNDER_PERFORMING_THRESHOLD].index.tolist()
```

**Output** (on modern_marketing.csv):
```
[]  # No regions trigger (small sample data)
```

### Example 4: Generate Bar Chart of Revenue by Region

```python
import matplotlib.pyplot as plt
by_region.plot(kind="bar", title="Net Revenue by Region", ylabel="USD")
plt.tight_layout()
plt.savefig("reports/revenue_by_region.png", dpi=150)
```
```

### Length: 3-5 examples, each ~10-20 lines

---

## Section 5: Edge Cases & Pitfalls

### Purpose
Pre-empt the **5 most common mistakes** an LLM would make. Save debugging time.

### Format: Numbered pitfalls with ❌ (wrong) and ✅ (right)

```markdown
## Edge Cases & Pitfalls

### 1. Currency strings
❌ `df["unit_price"].sum()` when column is `"$1,250.00"` → ERROR or wrong total
✅ Strip first: `df["unit_price"].str.replace("$","").str.replace(",","").astype(float).sum()`

### 2. Discount as percentage vs absolute
This dataset uses **absolute dollars** (discount=50.0 means $50 off, not 50%).
❌ `quantity × unit_price × (1 - discount/100)`  → 10x wrong values
✅ `quantity × unit_price - discount`

### 3. Region enum mismatch
- `standard_sales.csv`: US, EMEA, APAC
- `modern_marketing.csv`: US, EMEA, LATAM (no APAC)
- Combined analysis: LATAM defaults to 0% tax (Section 3.3) and may be flagged

### 4. Missing date column
`modern_marketing.csv` has NO date column.
→ Use file mtime as proxy, OR ask user, OR mark rows as "unknown date"

### 5. Negative quantities
Treat negative quantity as a **refund** (invert revenue sign, exclude from "completed sales").
❌ Include refunds in total revenue → overstates earnings
✅ Filter: `df = df[df["quantity"] > 0]` for revenue analysis
```

### What to AVOID in this section
- ❌ Generic pitfalls ("Handle null values")
- ❌ Theoretically-possible-but-unlikely scenarios
- ✅ Real failures we've actually seen

### Length: 3-7 pitfalls

---

## Comparison with `sales_analytics` (Our Existing Gold Standard)

| Aspect | `sales_analytics` | Refined Template | Gap |
|---|---|---|---|
| Schema documentation | ✓ (tables + columns) | ✓ + Aliases + Type quirks | Aliases & quirks missing |
| Column data types | ✗ (only inferred from name) | ✓ explicit | Improve |
| Column semantics | ✗ (just column names) | ✓ "Semantic" column | Improve |
| Column usage hints | ✗ | ✓ "Usage" column | Improve |
| Business logic rules | ✓ 4 rules | Same, but more precise | Equal |
| Few-shot SQL examples | ✓ 1 SQL example | ✓ 3-5 multi-format examples | More examples needed |
| Chart guidance | ✓ with type heuristics | ✓ same | Equal |
| Edge cases | ✗ | ✓ | Missing in original |

**Action**: Refactor `sales_analytics` to include Aliases + Type quirks + Edge Cases sections.

---

## Migration Path for Existing Skills

### `finance_pro` (currently)
- ✅ Has tax rate rules (Section 3 ✓)
- ❌ No data source samples (Section 1 missing)
- ❌ No alias map for column names (Section 2 partial)
- ❌ No few-shot examples (Section 4 missing)
- ❌ No edge cases (Section 5 missing)

**Recommendation**: Add Sections 1, 4, 5 to bring to template standard.

### `market_wizard` (currently)
- ❌ No structured sections at all
- ❌ No metadata table
- ❌ No few-shot examples

**Recommendation**: Apply full 5-section template (this skill is most in need).

### `unit-test-writer` (personal)
- ❌ Doesn't fit this template (it's code-generation, not data analysis)
- Use a different template for code-gen skills (separate doc TBD)

---

## When to Add/Remove Sections

| Situation | Action |
|---|---|
| Skill has 1 source file | Section 1 is short — just 1 file path + 1 sample |
| Skill has many sources (DBs, APIs, CSVs) | Section 1 grows — list each with sample |
| Column set is stable | Section 2 stays fixed |
| Column set varies by query | Section 2 includes "common vs. rare columns" |
| Domain is well-known (e.g., SQL) | Section 3 is short |
| Domain is opinionated (e.g., tax rules) | Section 3 is detailed |
| Few standard queries | Section 4 has 2-3 examples |
| Many edge cases per query | Section 4 has 5+ examples |
| LLM makes consistent mistakes | Section 5 grows with each discovered pitfall |
| LLM is reliable | Section 5 can be removed |

---

## Reference: SKILL.md Frontmatter

Every SKILL.md must start with YAML frontmatter:

```yaml
---
name: kebab-case-id       # REQUIRED: lowercase alphanumeric + single hyphens
description: <one-liner>  # REQUIRED: what the skill does + when to use it
---
```

### Name requirements
- Lowercase alphanumeric with **single hyphens only**
- No spaces, no underscores, no double hyphens
- Must match the directory name
- Must match the directory's kebab-case path

### Description requirements
- One sentence (≤200 chars recommended)
- Mentions **what** it does AND **when** to use it
- Example: `"Database schema and business logic for sales data analysis including customers, orders, and revenue."`

---

## Anti-patterns

❌ **Vague description**: "A data skill."
✅ **Specific description**: "Database schema and business logic for sales data analysis including customers, orders, and revenue."

❌ **Huge SKILL.md** (1000+ lines)
✅ **Focused SKILL.md** (50-200 lines), link out to detail docs

❌ **Embedding SQL/Python code in markdown instead of a separate script**
✅ **Reference a script** in the skill folder (e.g., `helper.py`) and document its API

❌ **Assuming LLM knows domain conventions** ("Use the standard date format")
✅ **Explicit formats** with examples ("YYYY-MM-DD; example: 2024-01-15")

❌ **Out-of-date data samples** that don't match the current data file
✅ **Re-validate samples quarterly** or after each data schema change

---

## TL;DR — The 30-Second Version

When writing a SKILL.md, ask:

1. **Data Source**: Have I shown the agent what the data looks like in raw form?
2. **Column Metadata**: Does each column have name + type + semantic + usage?
3. **Business Logic**: Are all formulas and thresholds explicit?
4. **Few-shot**: Are there 3-5 copy-paste-runnable examples?
5. **Edge Cases**: Have I listed the 3-7 most likely mistakes?

If yes to all, the skill is ready for production use.

---

## See Also

- [Phase 6 README](./phase6/README.md) — Skill as the hub (target architecture)
- `backend/notebooks/module-5/skills/sales_analytics/SKILL.md` — Gold standard example
- `backend/notebooks/module-5/skills/finance_pro/SKILL.md` — Needs migration
- `backend/notebooks/module-5/skills/market_wizard/SKILL.md` — Needs full rewrite
- `backend/services/skill_agent_demo.py` — Standalone SkillsMiddleware demo
- `backend/services/skill_agent_subagents_demo.py` — Subagent-per-skill demo