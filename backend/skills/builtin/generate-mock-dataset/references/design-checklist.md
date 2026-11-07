# Dataset design checklist

Every row is a decision with a consequence. The "if omitted" column is what actually broke (or would have
broken) in the ABC build.

## Structure

| item | question | if omitted |
|---|---|---|
| primary keys | does every entity have one column that identifies the thing? | an aggregate needs a grain; the ontology refuses `:grain` and the metric never exists |
| explicit grain | what is one row of the biggest table? | "破损率" becomes ambiguous (per stop / per trip / per box) and two reports disagree |
| dimension cardinality | does the column have 2–10 values (dimension) or 800 (identity)? | a "region" with 800 values cannot be grouped; the board shows a ranked list of labels |
| declared FKs | is every reference a real FK (and is it NULLable on purpose)? | joins get guessed by column-name coincidence; the ontology refuses paths it should have |
| 1:1 vs 1:N | is a driver bound to one vehicle? | an aggregate fans out and every count doubles |
| snapshot columns | did capacity/price at the time of the event differ from today's? | "超载" is recomputed against today's capacity and the history silently rewrites itself |
| versioned plans | does the plan change mid-window (并线)? | the regime shift is invisible and the demo's best finding disappears |

## Volume and time

| item | question | if omitted |
|---|---|---|
| volumes derived from the story | "90 天 × 45 趟/天" or a round `4,000`? | the customer checks the number you quoted, finds it wrong, and stops trusting the rest |
| a fixed historical window | which dates, and does `now()` fall inside it? | a `now()-90d` guard window returns 0 rows and every metric looks broken |
| `date_range` printed by introspection | is it recent (window OK) or historical (refuse)? | the guard's default silently changes what a metric means |
| per-period stability | is each day/week the same shape, or does it drift? | a week chart reads as a trend when it is only noise |

## The five pathologies worth keeping

1. **a constant column** — pick one column that would be a natural breakdown (complaint kind) and give it
   one value. Consequence: the ontology refuses the breakdown; the dashboard shows a one-bar chart as
   evidence.
2. **a single timestamp** — write all rows with one instant. Consequence: trends must be refused, and the
   refusal is the finding ("batch backfill").
3. **a large NULL group with a real meaning** — unjudged liability (46%), missing handler (27.8%).
   Consequence: `SUM` ignores them; a per-group panel must show 未判定 as its own cell, never 0.
4. **a table too small for the question** — 3 hours of telemetry. Consequence: "temperature trend" is
   refused; only "excursion stops" is answerable.
5. **plan vs actual that do not join** — `route_stops` vs `stops` share 75 of 51,210 rows. Consequence:
   the achievement rate is a declared refusal, not a wrong number.

## Verification, per item

Each claim goes into `<dataset>.dataset.json`:

```jsonc
{ "id": "overload_regime", "why": "超载是并线的后果，不是常态",
  "sql": "SELECT r.version, round(1.0*count(*) FILTER (WHERE t.load_weight >= t.weight_capacity_snapshot)/count(*),3) FROM trips t JOIN routes r ON r.id=t.route_id GROUP BY 1",
  "expect": { "v1": 0.02, "v2": 0.802 } }
```

- `expect` — exact (dict = per group, scalar = single number)
- `expect_range` — inclusive band, for a distribution that should be *around* a value
- `constant_columns` — verified as `count(DISTINCT col) = 1`
- `null_rates` — verified inside `[min, max]`

A claim with neither `expect` nor `expect_range` is reported `NOT RUN — the claim is not testable`, which is
the honest state for "the data feels right".

## Two rules that keep the generator honest

- **the spec is written first or immediately after**, never "later": a dataset without a spec is a pile of
  rows nobody can re-verify.
- **the generator is referenced by path and seed** in the spec's `_doc`, so a rerun is reproducible
  (`SEED = 20251106`, `--reset`).
