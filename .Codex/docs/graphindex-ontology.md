# GraphIndex Enrichment Ontology

Spec for the enriched document-index model: typed entities, document
categories, and LLM-generated tags, layered on top of the existing
routing metadata (`what_this_document_is_about`, `supported_queries`,
`out_of_scope`, `few_shot`).

Grounded in the `agent-workspace/reports/` corpus (company analyses,
industry analyses, comparisons, surveys, dossiers, strategic frameworks,
filings, dashboards) and mapped to standard ontologies where they fit.

## Design principles

- **Controlled + LLM maps**: enum fields are hard-validated by Pydantic;
  the LLM must pick from the controlled vocabularies below. Unknown values
  normalize to `other` in the parser — never fail the whole node.
- **Layered hybrid, not wholesale import**: no single standard covers
  business-intelligence reports, so each dimension anchors to the
  standard that fits it (see per-dimension notes).
- **Backward compatible**: new fields default to empty (`""` / `[]`), so
  existing nodes and the routing/scoring flow are untouched.

## 1. Entities

`[{ name, entity_type, role }]` — typed noun entities mentioned in the
document. `name` = exact surface form in the doc. Capped at 20.

| `entity_type` | Standard anchor | Meaning | Example |
|---|---|---|---|
| `Organization` | FIBO BusinessEntity | company / institution / agency | Starbucks, SEC |
| `Industry` | GICS sector/industry | the industry the doc concerns | Coffee, EV |
| `Person` | FIBO Person / IPTC concept-type | named person | Elon Musk |
| `Product` | FIBO Product | product / service / offering | Falcon 1, K-Cups |
| `Brand` | FIBO Brand | brand / trademark | Starbucks brand |
| `Geography` | ISO 3166 / IPTC worldregion | country / region / market | China, US |
| `Metric` | IFRS/XBRL concept | financial or operational KPI | revenue, CAGR |
| `Department` | functional taxonomy | org function / dept | Finance, HR Ops |
| `Concept` | IPTC generic concept | key noun, not a named entity | supply chain, electrification |

`role` ∈ `{subject, competitor, partner, author, source, market, other}` —
default `other`.

## 2. Categories

`{ genre, primary_subject, subjects, question_types, financial_metrics }`

### 2.1 genre — document kind (corpus-derived)

`company_analysis` · `industry_analysis` · `comparison` · `survey` ·
`dossier` · `strategic_framework` · `financial_data` · `source_document` ·
`filing` · `dashboard` · `other`

### 2.2 primary_subject — IPTC Media Topics top-level aligned

`economy_business_finance` (IPTC 04000000) · `science_technology` ·
`labour` · `environment` · `health` · `education` · `society` ·
`politics` · `other`

### 2.3 subjects — level-2 topics (≤ 5)

Semi-freeform, guided by the corpus's recurring areas: financial
performance, market position, product portfolio, technology & innovation,
operations & supply chain, strategy, organization & governance,
regulatory & compliance, transformation, customer support.

### 2.4 question_types — what the doc can answer (≤ 3)

`factual` · `financial_metric` · `comparison` · `trend_analysis` ·
`customer_support` · `regulatory` · `strategy_recommendation` · `other`

### 2.5 financial_metrics — IFRS/XBRL anchored (≤ 10)

Only when the document is finance-related; values drawn from IFRS concept
groups (IFRS 18 statement-of-profit categories: Operating / Investing /
Financing / Income Taxes / Discontinued Operations), e.g. `revenue`,
`operating_profit`, `net_income`, `ebitda_margin`, `current_assets`,
`net_cash_flow`, `cagr`.

## 3. Tags

Open vocabulary, but derived from the top entities + key topics.
≤ 10, lowercase-normalized, no standalone dates/numbers.

## 4. Storage mapping (Neo4j node)

- `entities_json` — JSON string `[{name, entity_type, role}]`
  (mirrors the existing `few_shot_json` pattern)
- `categories_genre`, `categories_primary_subject` — scalar
- `categories_subjects`, `question_types`, `financial_metrics` — string lists
- `tags` — **merged** source tags ∪ LLM tags (deduped, capped at 20)

## 5. Prompt behavior

- Prompt gains an "Extract entities / classify genre & subjects / pick
  question types / tag the document" section; existing `out_of_scope`
  exact-name rules are unchanged.
- Structured-output failure falls back to the plain-text JSON path with the
  same extended schema.
- Parser: enum values normalized case-insensitively, unknown → `other`;
  lists truncated to their caps; `financial_metrics` dropped when the doc
  is non-financial.
