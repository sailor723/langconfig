---
name: generate-mock-dataset
description: Use when a business story (a customer call, a written brief, a slide) has to become a PostgreSQL dataset that can be DEMONSTRATED on — deterministic, volume-consistent, with the failures planted where the story says they come from and the data pathologies (constant columns, unjudged rows, a missing record) present on purpose; every claim it makes is a query in a spec file, and the spec is the gate
tags: [mock-data, synthetic-data, postgres, dataset, demo, gating]
triggers:
  - When asked to create mock / synthetic / demo data from a described business
  - When a demo needs the pain points to be VISIBLE in the numbers, not asserted in a slide
  - When an ontology build needs a database whose story it can prove
  - When "make up some data" would otherwise produce data that answers different questions
version: 1.0
author: weiping

# What the dataset is for decides how it is shaped: an ontology build needs dimensions and pathologies,
# a demo needs the pain points, a benchmark needs volume. Say which, because it changes the design.
params:
  dataset_name:
    label: 数据集
    description: the database name the data lands in (e.g. abc_coldchain)
    required: true
  generator:
    label: 生成器路径
    description: where the deterministic generator script lives (e.g. backend/skills/builtin/generate-mock-dataset/scripts/gen_abc.py)
    required: false
    default: "backend/skills/builtin/generate-mock-dataset/scripts/gen_{dataset_name}.py"
---

# Generate a mock dataset from a business story

The difference between mock data and a mock *dataset*: mock data fills tables, a mock dataset makes the
story's claims true and **checkable**. Every claim becomes a query in `<dataset>.dataset.json`, so a green
run means "the data still says what the brief says" — and a red one names the claim that rotted.

## 0. Read the story for STRUCTURE, not adjectives

From the brief, extract only what becomes a column, a row count or a relationship:

| sentence in the brief | becomes |
|---|---|
| 「约60台司机自有的冷藏车队（12吨3台、10吨5台、8吨35台、5吨6台、3吨11台）」 | `vehicles(60)` with `tonnage` distribution EXACTLY as stated (it is a fact the customer will check) |
| 「一车一人，司机按月扣还购车贷款」 | `drivers.vehicle_id` 1:1, and the missing `loan_*` column is itself a finding |
| 「把原本每天约50条固定配送路线强行压缩至40条」 | `routes.version` v1/v2 + `effective_from` → a REGIME the data can be split on |
| 「几乎每趟车都在挑战超载极限」 | `load_*` vs `*_capacity_snapshot` at dispatch time (a snapshot, not a join to today's capacity) |
| 「日结临时工，几乎每天都在换新面孔」 | `handlers(first_day, days_worked, agency)` → turnover is measurable |
| 「司机和日结工互相推诿」 | `complaints.liability` with a large NULL group — the adjudication gap |
| 「调度凭同情心排轻松线」 | **not representable today** → the dataset must NOT pretend: record the outcome (trips) and let the ontology refuse the intent |

If a pain point has no column, that is the finding to keep: the ontology will refuse it by name, and the
dashboard will show the hole. Do not invent a proxy column to make the demo look complete.

## 1. Design: entities → grain → volumes → invariants

1. **entities** — one row per thing the business names, with a real primary key.
2. **grain** — the fact you will count: a stop is one store visit, a trip is one vehicle-day-route. Write
   it down; it decides every metric later.
3. **volumes** — derive from the story ("90 天 × 45 趟/天 = 4,050"), never from a round number that makes
   the story false. Keep a helper that prints the totals the brief implies.
4. **invariants** — the claims, as SQL (see `check_dataset.py`). Include at least one claim per pain point
   the customer mentioned, and at least one identity (child rows per parent, sums that must hold).

## 2. Plant the failures where the story puts them

Random failures make a demo that proves nothing. Measured on ABC:

| planted | mechanism | what becomes visible |
|---|---|---|
| 超载 2% → 80% after 并线 | capacity snapshot fixed per vehicle; route stops 10.2 → 15.7 | `overloadRateByRouteVersion` |
| 倒温 mostly on old vehicles | excursion probability keyed to `age_years` | `tempExcursionStops` per vehicle |
| 破损 on day-labourers in their first week | damage keyed to `handlers.days_worked` | damage 4.5 vs 1.7 boxes / 1k stops |
| 客诉 follows late + excursion | complaints generated per failed stop | `complaintCountByLiability` |
| 路权 conflict | `emission` + `core_zone_permit` set so 国四 36 台 have none | `permitCoverage` 23.3% |

## 3. Include the pathologies ON PURPOSE

A dataset that is clean teaches the wrong lessons. Each of these exists in ABC and each turned into an
ontology gate:

- **a constant column** (`complaints.kind` = only `late`) → "cannot do a complaint-type breakdown" is a
  finding, not a bug;
- **a single timestamp for all rows** (`opened_at` identical) → the trend chart has ONE bar, and that bar is
  the evidence the timestamps were batch-backfilled;
- **a large NULL group** (`liability` NULL 46.1%) → unjudged liability is a real group; its amount is NULL,
  not 0;
- **a table that is too small for the question** (3 hours of telemetry) → temperature trends must be refused;
- **plan vs actual that do not join** (`route_stops` vs `stops`: 75 of 51,210 stops share a store) → the
  achievement rate is unrepeatable and stays a declared refusal.

## 4. Determinism and reset

- **SEED constant at the top.** A number in a gate or a screenshot must never move on its own; measured
  lesson: a gate comparing a `now()`-relative number to a constant decays into a false alarm.
- `--reset` drops and recreates (idempotent), because a demo is re-run often.
- Generated ids are stable across runs; never rely on `serial` ordering for anything a query compares.
- Time: put the data in a **fixed historical window** and say so (`2026-08-08 → 2026-11`). Then
  `guard.default_window_days` must be `0` (refuse a now-relative window) or every metric silently returns
  nothing.

## 5. Verify with the spec, then hand off

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY <this skill>/scripts/check_dataset.py --spec <this skill>/fixtures/abc_coldchain.dataset.json
#   → 53 checks, 0 failed   (volume, FK, planted invariants, constant columns, NULL rates)
```

Then the dataset feeds the normal path: `build-ontology-from-db` (introspect → declarations → gates →
dashboard). The spec file is the contract between the two skills: the ontology's `:businessDescription`
should quote the same numbers the spec asserts.

## Anti-patterns

- random data with a story pasted over it (nothing proves anything);
- a "clean" dataset with no NULLs and no constant columns (the demo then claims a competence the real data
  does not support);
- volumes chosen for roundness so `4,050` becomes `4,000`;
- a pain point represented by a proxy column the business never had (write it in `cannot_see` instead);
- `now()`-relative dates in a fixed historical dataset — every window then returns nothing.

## References

- `references/design-checklist.md` — the checklist, each item with its verification query and the ontology
  consequence of omitting it.
- `references/abc-case.md` — the full worked example (schema, volumes, planted signals, measured numbers).
- `scripts/check_dataset.py` — the spec checker (this skill's gate).
- The generator it was distilled from: `<this skill>/scripts/gen_abc.py` (SEED 20251106, `--reset`).
