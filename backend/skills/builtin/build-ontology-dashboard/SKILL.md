---
name: build-ontology-dashboard
description: Use when an ontology needs a dashboard — a declaration (dashboard.json) of which COMPILED metrics each panel shows, an opening assessment that quotes only compiled numbers, charts that need layout (sankey/bubble/treemap), and cross-filtering that recompiles server-side; walks the order that keeps a board honest (declaration → compile → guard → gate → only then the page) and refuses to let a panel invent a number the ontology does not declare
tags: [ontology, dashboard, semantic-layer, metrics, sql, gating]
triggers:
  - When asked to build or extend a dashboard / 看板 / 经营看板 on top of an ontology
  - When a dashboard shows a number nobody can trace back to a declaration
  - When panels must cross-filter and the filter cannot be a client-side guess
  - When an opening "assessment" must not drift from the numbers it talks about
version: 1.0
author: weiping

# Point the skill at one ontology. The dashboard is `<profile dir>/dashboard.json`; nothing else is needed
# to know where it lives, which is why a missing file is a real answer ("this ontology has no dashboard").
params:
  ontology_key:
    label: 本体
    description: the folder under ontologies/ whose dashboard is being built (e.g. logistics)
    required: true
  profile_file:
    label: profile 文件名
    description: the workbench profile inside that folder
    required: false
    default: "{ontology_key}_settings.json"
---

# Build an ontology dashboard

A dashboard is a **declaration**, not a page of queries. `dashboard.json` says *which compiled metric*
each panel shows, *cut by what*, what an unfilled hole costs, and how a filtered view is allowed to differ.
The page draws. The compiler answers. Nothing in the middle computes a number.

This skill is the order that keeps that true, plus the gates that make each step bite.

## 0. What must already be true

The dashboard rides on capabilities the ontology must DECLARE. Check these before writing a panel — each
missing one turns into a refusal card, which is fine, but knowing which is which is the difference between
a design and a pile of holes:

| capability | declaration | refusal when absent |
|---|---|---|
| a rate per group | `:aggregate "ratio_of_sums"` + `:groupBy`, **both sides at the same grain** | *"grouped ratio compiles only when both sides share the grain"* |
| a time series | `:timeBucket "week"` + the grain's own `:timeColumn` | *"declares :timeBucket … but :Stop declares no :timeColumn"* |
| an existence fact | `owl:someValuesFrom` restriction + the inverse link | *"has no owl:equivalentClass axiom"* |
| cross-filtering | the dimension must be a `:groupBy` of a declared metric | *"cannot filter :Trip by :storeZone"* |

Ask the compiler, never the source: `python backend/features/ontology/compiler/run_dashboard.py --profile … --metric <name>`.

## 1. Scaffold from what is declared (never from what you wish)

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
cd <ontology repo>/retail_graph
$PY ../backend/skills/builtin/build-ontology-dashboard/scripts/scaffold_dashboard.py \
    --profile ../ontologies/logistics/logistics_settings.json --out /tmp/dashboard.json
```

It emits a starter `dashboard.json` built from the compiled graph: KPIs from ungrouped metrics, one panel
per grouped metric with a shape chosen from the declaration (1 key → series/ranked/composition, 2 keys →
matrix), and a `holes` list containing every metric that REFUSES **with the reason it must refuse**. It
does not invent thresholds, sentences or event markers — it prints exactly what it left for you.

Read the scaffold, then delete most of it. A dashboard with 30 panels is a screenshot of the ontology, not
a board: keep the 8–14 that answer the business's questions and put the rest behind a drill.

## 2. The opening assessment is the hardest part

`briefing` is prose with **no hand-typed numbers**: every value is `{metric}` (scalar) or `{metric:key}`
(a group row) or `{metric:key#key}` (echo the KEY, for a plate/code that contains digits). Gate `D7` strips
the placeholders and fails on any remaining digit — measured: a first draft typed "50 条压成 40 条" and
quoted a trip count in a sentence about stops-per-route, and the fix was to *declare* `routeCountByVersion`
and `stopsPerRouteByVersion`, not to reword the sentence.

`policy` holds the thresholds that turn a description into a judgement. Every threshold carries
`assumed: true` until a human confirms it, and the UI labels it 假设. A verdict the gate recomputes from
the metric value — the payload's own `breached` flag is never trusted.

`cannot_see` is part of the assessment. It is where the data's pathologies are stated (constant timestamps,
unrecorded decisions, missing financial fields) instead of being silently averaged away.

## 3. Panels: pick the smallest kind that shows the finding

See `references/chart-kinds.md` for the ten kinds, the fields each needs, and what the gate checks. Rules
that keep panels honest:

- **the band/cell/dot is a declared value.** A Sankey's link is `metric:key`, not a sum of two panels.
- **a hole is a panel.** A metric that refuses appears as a refusal card naming the missing declaration,
  or as a declared `holes` entry with the refusal it expects (`D4` fails a hole that starts answering).
- **a NULL group is a group.** Unjudged liability is a cell labelled 未判定, never a 0 and never dropped.
- **an event marker needs a time axis** (`D6`), and one on a categorical axis is a lie about causality.

## 4. Cross-filter: recompile, never re-weight

`?filter=<dimension>:<value>` goes to the runner, which passes it to the compiler
(`sqlgen.apply_dimension_filters`). The filter is applied as a derived table with the grain's own name, so
**every** `FROM grain` occurrence is narrowed — which is the only way a two-subquery RATIO is filtered on
both sides. The value must be one the declaration offers, otherwise the runner exits 2 with the allowed
list: `routeVersion=v9` would otherwise answer a confident `0`.

What the board must then show, and what `F1` checks:

| rule | why | gate |
|---|---|---|
| every `emit_filter.dimension` is a `:groupBy` of a declared metric | the value set is a declaration, not a UI list | `F1a` |
| Σ(metric \| dim=v) over v == the unfiltered metric | a filter that only reached the numerator | `F1b` |
| `overloadRate` filtered to v2 == the v2 row of `overloadRateByRouteVersion` | the one check that proves both sides | `F1c` |
| an unreachable dimension refuses BY NAME | cutting by store zone cannot change trip counts | `F1d` |
| an unknown value is refused by the runner | a silent 0 is the worst answer | `F1e` |

A view whose subject is the missing record (e.g. a panel measuring "no dispatch decision is recorded")
declares `filter_not_applicable` and carries the 不适用筛选 badge: a filtered board must never look
uniformly filtered when one block is not.

## 5. Gate, then show

```bash
$PY check_dashboard.py --profile ../ontologies/logistics/logistics_settings.json
$PY check_dashboard.py --profile … 2>&1 | grep -E 'FAIL|checks,'
```

`D0`–`D9` + `F1`: 196 checks on the logistics board (see `references/gates.md`). Two shapes of failure
prove it bites — mutate a declaration and watch the right family go red:

- point a panel at a misspelled metric → `D0` names the panel and the metric;
- delete the `FILTER (WHERE …)` from the grouped-ratio path → `D3` weighted identities **and** `D5`'s
  independent SQL go red together.

A gate that cannot fail is decoration. If you add a check, add its mutation.

## 6. What the runner returns, and what the page may do with it

`GET /api/ontology/<key>/dashboard/panels[?filter=dim:value]` → the declaration plus, per metric, `status`,
`label`, `unit`, `keys`, `rows`, `sql`, `guard_notes`, `plan_rows`. The page may format and lay out; it may
not add, divide or weight. The one arithmetic-adjacent thing it does — hiding rows that do not match a
selection — is layout, and it says so.

## Anti-patterns (all of these were bugs here)

- a chart that sums two panels to make one band (breaks `D8`'s conservation);
- a "the 20 worst vehicles" list rendered from a metric compiled `ORDER BY … DESC` without
  `client_sort: true` (`D2`), so the board showed the best 20;
- a histogram over a constant column drawn as a trend (one bucket is the finding, say it);
- a filter applied in the browser "just for the visible panel";
- a dashboard that silently drops a panel whose metric refuses.

## References

- `references/declaration.md` — the `dashboard.json` contract, key by key, with the reason each exists.
- `references/chart-kinds.md` — the ten panel kinds and what each needs.
- `references/gates.md` — `D0`–`D9` + `F1`, how each bites, and the mutations that prove it.
- `scripts/scaffold_dashboard.py` — starter declaration from the compiled graph.
- The working example: `ontologies/logistics/dashboard.json` (16 panels, 196-check gate).
