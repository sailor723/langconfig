# `dashboard.json` — the contract

One file next to the profile (`<profile dir>/dashboard.json`). It contains **no SQL and no numbers**: it
names metrics, dimensions and the sentences that talk about them. `backend/features/ontology/compiler/run_dashboard.py`
compiles it; `backend/features/ontology/gates/check_dashboard.py` gates it; the page only lays it out.

```jsonc
{
  "_doc":       "what this file is for — every dashboard.json starts with one",
  "version":    1,
  "ontology":   "logistics",
  "title":      "ABC 冷链 · 经营看板",
  "subtitle":   "口径来自 ontologies/logistics/metrics_ext.ttl",

  "events":     [ … ],   // dated markers; each names a metric that has a time axis
  "policy":     [ … ],   // the thresholds a judgement is made against
  "briefing":   { … },   // the opening assessment, in prose with placeholders
  "kpis":       [ … ],   // the headline numbers
  "panels":     [ … ],   // the charts
  "holes":      [ … ],   // metrics that MUST refuse, with the reason they must
  "cross_filter":[ … ]   // which panel emits which dimension (v1: single dimension, single value)
}
```

## `kpis`

```jsonc
{ "metric": "overloadRate", "note": "载重/容积/箱数任一触顶" }
```

A metric with no `:groupBy` and one row. The label and unit come from the declaration (`rdfs:label`,
`:unit`), never from this file — a board and a workbench must not disagree about what a number is.

## `events`

```jsonc
{ "id": "merge", "at": "2026-09-22", "label": "并线生效：50 → 40 条线路",
  "kind": "regime", "metric": "tripCountByWeek",
  "note": "routes.version v2 的 effective_from（从数据里读出来的事实）" }
```

`D6` requires the metric to have a `:timeBucket` and to return buckets on **both sides** of `at`. A marker
on a categorical axis is a claim about cause that the data does not support.

## `policy`

```jsonc
{ "id": "overload", "label": "超载率红线", "metric": "overloadRate",
  "op": ">", "value": 0.05,
  "assumed": true, "why": "5% 是初始红线，业务未确认" }
```

- `op` ∈ `> >= < <= ==`; the verdict is computed from the metric's scalar value.
- `assumed: true` means "our guess, labelled as such in the UI"; `confirmed: true` means a human owns it.
  `D7` fails a threshold that declares neither — an unowned number deciding red/green is the bug.
- A threshold on a metric that refuses makes its claim "cannot be assessed", not "green".

## `briefing`

```jsonc
{
  "headline": "{overloadRate} 的行程在超载，而并线之后它变成 {overloadRateByRouteVersion:v2}；…",
  "claims": [
    { "id": "ontime", "verdict_by": "ontime",
      "text": "准时率从 {stopOnTimeRateByRouteVersion:v1} 降到 {stopOnTimeRateByRouteVersion:v2}；车队整体 {stopOnTimeRate}。",
      "note": "按站点计，不按趟计。" }
  ],
  "cannot_see": [ "并线补偿条款与运价…", "「人情调度」本身…" ],
  "next": "先做两件不依赖算法的事：…"
}
```

Placeholders:

| form | renders |
|---|---|
| `{metric}` | the scalar (refuses if the metric is grouped: a key is required) |
| `{metric:key}` | that group's value; multi-key groups use `key1|key2`, case-insensitive |
| `{metric:key#key}` | the KEY itself (for a plate/code that contains digits) |

Formatting is `run_dashboard._fmt` (ratios → %, money → ¥, integral counts → no decimals) — one
implementation, so the prose, the KPI cards and the charts cannot disagree.

`verdict_by` names a `policy` id; the claim inherits that policy's colour and the gate fails a claim judged
by an undeclared policy.

## `panels`

Every panel has `id`, `kind`, `title`, `question` (the business question it answers — the page shows it,
and it is the cheapest documentation a board can have), and the fields its kind needs. Common optional
fields:

| field | meaning |
|---|---|
| `view: "custom"` | the panel exists because a generic one would hide the finding (say why in `why_custom`) |
| `note` | shown in the 口径 drawer: how to read this number |
| `expect` | why a one-row series is legitimate (a constant column IS a finding) |
| `emit_filter` | `{ "dimension": "plate", "column": "key1" }` — clicking a value sets the board's filter |
| `accepts_filter` | optional restriction; absent = any reachable dimension |
| `filter_not_applicable` | a view whose subject is the missing record; shows the badge |
| `client_sort` | the panel needs the LOW end of a metric the compiler orders `DESC` (`D2`) |
| `null_label` | the label for a NULL group (`未判定`) — required when the rows contain one |

## `holes`

```jsonc
{ "metric": "atRiskDrivers",
  "expect_refusal": ":AtRiskDriver has no owl:equivalentClass axiom",
  "why": "「高风险」的判定线是客户政策，库里没有。" }
```

Two-sided: the metric must REFUSE and the refusal must contain `expect_refusal`. `D4` fails when a hole
starts answering (a stale declaration lies in both directions). Refusals that are not declared here are
live failures — the board is not allowed to quietly widen its own holes.

## `cross_filter`

```jsonc
{ "dimension": "plate", "label": "车辆", "metric_panel": "damage_ranked", "apply_to": ["ontime_ranked"] }
```

v1 is one dimension, one value: clicking a value replaces the filter, clicking it again clears it. Multiple
keys per cell (region × liability) need intersection semantics and are deliberately out of scope until a
gate can prove them.
