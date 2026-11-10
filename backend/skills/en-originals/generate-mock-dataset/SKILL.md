---
name: generate-mock-dataset
description: Use when a business story (a customer call, a written brief, a slide) has to become a PostgreSQL dataset that can be DEMONSTRATED on — deterministic, volume-consistent, with the failures planted where the story says they come from and the data pathologies (constant columns, unjudged rows, a missing record) present on purpose; every claim it makes is a query in a spec file, and the spec is the gate.
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
    label: 数据集（建议名）
    description: >-
      A SUGGESTION, not an order: the database the data lands in. Confirm the final name with the user before
      creating anything (step 0c). The agent's copy of this parameter is what makes it propose one instead of
      inventing one silently.
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

## 0a. Read the brief — with the right reader

- **`.md` / `.txt` / `.json` / `.csv`** → `read_file`.
- **`.pdf` / `.docx` / `.pptx` / `.xlsx`** → `read_any_file`. It returns the *text*: headings, tables, slide
  text, sheet by sheet. A scanned PDF or an image goes through OCR there too.
- **If a read comes back as `<w:p>`, `<a:tbl>`, `PK\x03\x04`, or base64, you read raw bytes — not text.**
  Stop, do not `unzip`/`cat`/`strings` the document, do not decode its XML by hand, and **never** paste the
  document back as your answer. Switch to `read_any_file` and read it again.

That failure is measured, not hypothetical: an agent given a 16 KB Word brief got the raw OOXML, worked
around it with `unzip … word/document.xml`, and returned 143 KB of tag soup as the "deliverable" — no
generator, no tables, no dataset. Reading the input is step zero; everything after it depends on the text.

**A document is not a schema.** The brief gives entities, grain, volumes and relationships; the columns are
yours to design. Never answer a data-generation request by restating the brief.

## 0b. Read the story for STRUCTURE, not adjectives

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

## 0c. Draft the dataset MANIFEST — the name, the units, the caveats — and confirm it

A database name is one field of the dataset's identity, not the whole question. Writing the manifest FIRST is
what makes the rest answerable: the ontology builder reads `schema`, `units` and `nulls` to write its profile and
its axioms, the dashboard reads `units` for its labels, and an operator reads `checks` to know whether the numbers
in front of them are the numbers that were verified.

Write `generated/<slug>/manifest.json` (before creating anything) with this shape — fill what the brief answers,
leave the rest as `null` with a `questions` entry, and **mark the status `proposed`**:

```json
{
  "dataset":  {"name": "<proposed name>", "schema": "nass", "status": "proposed",
               "purpose": "one sentence: what this dataset exists for",
               "confirmed_by": null, "confirmed_at": null},
  "source":   {"system": "the exporting system the brief names (or 'synthesised')",
               "files": [{"name": "upload/x.docx", "sha256": "…"}],
               "generator": "generated/<slug>/gen.py", "seed": 20260101, "spec": "…dataset.json"},
  "time":     {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0, "timezone": "…",
               "relative_window": false, "as_of": "YYYY-MM-DD",
               "regimes": [{"date": "YYYY-MM-DD", "change": "what changed in the rules"}]},
  "units":    {"<column>": "boxes|kg|t|m3|HKD|%|count"},
  "nulls":    {"<table.column>": "unknown|not_judged|not_recorded|not_applicable (why)"},
  "pii":      [{"column": "<table.column>", "kind": "person_name|plate|phone", "handling": "synthetic|masked"}],
  "decisions": [{"id": "Q23", "text": "…", "source": "brief §… | chat YYYY-MM-DD", "status": "confirmed|proposed"}],
  "refused":  [{"name": "what the ontology must refuse", "why": "…", "missing": "the declaration it lacks"}],
  "handoff":  {"ontology_key": "<key>", "profile": "<key>/<key>_settings.json",
               "guard": {"default_window_days": 0, "big_tables": {"<schema.table>": "<time column>"}}},
  "checks":   {"invariants": 0, "result": null, "deterministic": null, "mutation_turns_red": null},
  "rows":     {"<schema.table>": 0},
  "questions": [{"id": "Q1", "ask": "the question, in the user's words", "blocks": "what cannot be decided without it"}]
}
```

**Four things only the user can settle** — ask them in the confirmation turn, in business terms, and put the
answer in the manifest (not only in the chat):

1. **currency** — money columns are numbers until someone says HKD / RMB / other.
2. **units** — `tonnage` t, `load_weight` kg, `load_volume` m3, `box_capacity` boxes: confirm or correct.
3. **PII** — driver names and plates: mask them, or keep readable names because the data is synthetic?
4. **time** — the timezone, and the window length (which decides whether a `now()`-relative guard window is
   meaningful at all; a fixed historical window means `default_window_days: 0`).

Then, and only then:

1. `psql -l` — say what already exists on this server.
2. Ask, in one line: **"数据集库名用 `<name>` 可以吗？"** plus what you will do:
   - does not exist → you `CREATE DATABASE` it and build there;
   - exists and is NOT yours → say what is in it, and do **not** overwrite without an explicit yes;
   - exists and is a previous build of yours → offer `--reset` (rebuild) or a new name.
3. **Nothing is created before the answers**: no database, no schema, no tables. Reading the brief and writing
   `ANALYSIS.md` + the manifest draft in that same turn is expected — that is how the user sees you understood
   before a database exists.
4. After the answers: set `dataset.status = "confirmed"`, `confirmed_by`, `confirmed_at`, fill `units`/`nulls`/
   `pii`/`time`, then build. Update the manifest at the end (`status: "built"`, `checks`, `rows`).

Why this step exists: the name used to be baked into the agent's configuration, so a second brief would have
landed in the first brief's database and nobody had agreed to that; the units and the currency were never written
down anywhere, so every downstream label had to guess.

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

## 3b. Write files in BOUNDED chunks (a 700-line tool call stalls)

A single `write_file` that carries the whole generator is one enormous tool-call argument stream. Measured twice
on this provider: the request streamed 28 chunks and then went silent for **600 s**, the turn was lost and the
user saw a spinner. So:

- write the generator in **sections of ≤ ~120 lines**: skeleton + helpers first, then one `edit_file` (or append)
  per table group, then `main()`;
- same for the spec: write the flat parts (`dataset`/`source`/`time`) first, then `invariants` in two or three
  passes;
- after each write, `wc -l` the file so you know it is really growing (a truncated write that "succeeded" is the
  failure mode this prevents);
- a huge single response is not a virtue: nobody reviews it in one go, and the provider may just stop.

## 3c. Measure with ONE query, not N queries

A number is a query, but N numbers are not N queries. Measured (2026-11-07, `new_coldchain`): the agent wanted trips
per day after the merge, so it issued `select count(*) … trip_date >= '2026-09-22' and trip_date < X` for X =
09-23, then again with a second `-c`, then a third … each call repeating every earlier query and adding one more.
After ten turns the command was thousands of characters of duplicated SQL, no number had been reported, and the
turn eventually died on a stalled stream.

Rules:

- **one aggregate, one statement**: `select trip_date, count(*) from trips group by 1 order by 1` answers the whole
  question; `select version, avg(planned_stops), … group by 1` answers the signal table;
- if a value must be measured, measure it in the SAME query that prints the label, and print all of them at once;
- never re-send a query you already sent; if you need it again, re-read the previous tool result instead;
- if two consecutive tool calls are ≥80 % identical, stop and change the approach — that is the loop, not progress.

## 4. Determinism and reset

- **SEED constant at the top.** A number in a gate or a screenshot must never move on its own; measured
  lesson: a gate comparing a `now()`-relative number to a constant decays into a false alarm.
- `--reset` drops and recreates (idempotent), because a demo is re-run often.
- Generated ids are stable across runs; never rely on `serial` ordering for anything a query compares.
- Time: put the data in a **fixed historical window** and say so (`2026-08-08 → 2026-11`). Then
  `guard.default_window_days` must be `0` (refuse a now-relative window) or every metric silently returns
  nothing.

## 4b. Delivery self-check — every line, before you answer

| must be true | how it is checked |
|---|---|
| the generator file exists at `generated/<dataset>/gen.py` | `ls` it |
| `SEED` is a constant at the top, `--reset` drops and recreates | `grep` for both |
| the spec exists at `generated/<dataset>/<dataset>.dataset.json` | `ls` it |
| `check_dataset.py --spec …` printed **`N checks, 0 failed`** | run it; quote the line |
| every hard fact in the brief is an assertion (counts, distributions, the 50→40 split) | open the spec and count them |
| every planted signal is asserted with a number | same |
| every deliberate pathology is asserted (a constant column, a NULL group, a table too small) | same |
| each pain point with no column is in `cannot_see` | `grep` it |
| **a rebuild changes nothing**: `gen.py --reset` twice gives identical numbers | compare the totals before/after, or a checksum of a key aggregate |
| **the spec can FAIL**: change one expectation by hand → it goes red, change it back → green | do this once, and say so; a spec nobody has ever seen fail is decoration |
| the manifest exists at `generated/<slug>/manifest.json` and its `dataset.status` is `built` | `cat` it |
| the manifest's `rows` equals what the database actually holds | `select count(*)` per table, compare |
| the manifest's `checks` equals what `check_dataset.py` printed | same run, same numbers |
| `units`, `nulls`, `pii`, `time.timezone` are filled — not `null` | a manifest with null units is a dataset nobody can label |

**A reply that answers without those artifacts is not a partial delivery; it is a failed run.** Say so
plainly rather than dressing it up.

## 5. Verify with the spec, then hand off

```bash
PY=<the app's own .venv: the interpreter that runs the backend>
$PY <this skill>/scripts/check_dataset.py --spec <this skill>/fixtures/abc_coldchain.dataset.json
#   → 53 checks, 0 failed   (volume, FK, planted invariants, constant columns, NULL rates)
```

Then the dataset feeds the normal path: `build-ontology-from-db` (introspect → declarations → gates →
dashboard). The spec file is the contract between the two skills: the ontology's `:businessDescription`
should quote the same numbers the spec asserts.

## Anti-patterns

- **answering with the document itself** — the brief (or its XML) restated as the "result". The deliverable
  is a generator, a spec and a check count, or it is a failure with a reason;
- **reading a binary document through a text path** (`unzip`/`cat`/XML parsing) instead of `read_any_file`;
- **building into a database the user did not confirm** (or overwriting one without asking): the name is a
  business decision, and a silent build is how the second brief lands in the first brief's database;
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
