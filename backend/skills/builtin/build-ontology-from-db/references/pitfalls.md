# The failure catalogue

Every entry was produced by a real build. **Read this after the first draft** — it explains most of
what goes wrong, and each one has a symptom you can recognise.

## Numbers that are wrong in a plausible way

### Integer division in a ratio
**Symptom:** a rate of 36.8 % reports as `0`.
**Cause:** `(SELECT count(*) …) / (SELECT count(*) …)` — two `bigint`s divide as integers.
**Fix:** cast the numerator: `(({num})::numeric) / NULLIF(({den}), 0)`.
**Detect:** assert `0 < rate < 1` (or `0 < rate < 100` with `:scale`) in the gate, not `rate >= 0`.

### `count(DISTINCT a, b)` is not a function
**Symptom:** `function count(bigint, integer) does not exist`.
**Cause:** a composite primary key pasted into `count(DISTINCT …)`.
**Fix:** a tuple — `count(DISTINCT (a, b))` — with every column qualified.
**Detect:** compile a grouped count on a composite-key class and execute it.

### Silent fan-out on a join
**Symptom:** a sum grows after adding a "harmless" join.
**Cause:** a many-to-many join counted or summed per row; or half a composite key.
**Fix:** `count(DISTINCT (pk…))`, or aggregate over the grain and join after.
**Detect:** compare against ground truth computed without the join.

### A metric that changes because a guardrail windowed it
**Symptom:** a metric reads 849.50 where the definition says 969.50.
**Cause:** the guard injected `placed_at >= now() - 90 days` into a declared metric.
**Fix:** metrics run in `mode="declared"` (never windowed); the scan is *reported*, the plan budget
refuses if it is too big.
**Detect:** the gate asserts the guarded number equals the unguarded number.

## Numbers that are empty but look like facts

### `now()`-relative window over historical data
**Symptom:** every page returns "0 rows" or `—`; nothing errors.
**Cause:** the data is 1992–1998 (TPC-H) or simply old (a mock dated last year), and the window is
`>= now() - 30 days`.
**Fix:** check `date_range` from the introspection brief. If the data is not recent, **refuse**
(`default_window_days: 0`) instead of narrowing. Make mock data use *today*, not a hard-coded date.
**Detect:** report "the injected window matched 0 rows" instead of returning an empty page silently.

### A group that is absent, not zero
**Symptom:** "Shenzhen" missing from a by-city report; someone reads it as zero.
**Fix:** say it — the metric returns the groups that exist. Do not zero-fill without labelling it.

## Joins and keys

### Half a composite key
**Symptom:** supply cost inflated ~2.4×; per-supplier rows multiplied.
**Fix:** `:physicalColumn "a, b"` + `:referencesKey "x, y"`; refuse when counts disagree.

### Guessing a join from a column name
**Symptom:** two different `customer_id`s joined; a plausible-looking wrong number.
**Fix:** only `:references` creates a path; a missing path is refused by name.

### A link with payload modelled as a link
**Symptom:** the link's own quantity disappears, or is duplicated onto both ends.
**Fix:** reify it (a class with two FKs and the payload) — and note the cost: the link becomes a
grain you can group by.

## Definitions

### Thresholds in several places
**Symptom:** two reports disagree by the threshold they used; nobody can change it once.
**Fix:** the threshold lives in the axiom, once.

### An axiom AND a declared predicate on one class
**Symptom:** the declared one silently wins; the axiom is dead text.
**Fix:** refuse the combination — it is ambiguous by construction.

### A definition with no row to attach to
**Symptom:** "over the last 30 days" ends up in SQL.
**Fix:** materialise a snapshot fact (`…_stats` with `window_days` in the key).

### A windowed definition whose window is a profile constant
**Symptom:** the user asks for 7 days, gets the profile's 90, and nothing says so.
**Fix:** either the question carries the window (and the page shows it), or the answer says which
window it used. Never both silently.

## Language and naming

### Property named after the column
**Symptom:** "revenue by region" refuses though the data has regions.
**Fix:** `:regionName` with `:physicalColumn "r_name"`; the local name is the question's word.

### A profile alias polluting another profile
**Symptom:** one dataset's "region → city" alias makes another dataset's real region object
unreachable.
**Fix:** aliases per profile; never in the shared table.

### Fixing Chinese (or any CJK) matching with a blunt rule
**Symptom:** an exact-label bonus fixed one profile and broke a gate in another.
**Fix:** develop against **all** profiles' gates at once; prefer proper tokenisation over scoring
hacks. If you cannot do it safely now, use an explicit per-profile phrase table and *label it as
such* — the answer says "recognised phrasing", not "natural language".

## Operations

### SQL accepted from the caller
**Symptom:** a teaching page posts a statement; the "no free-form SQL" promise is quietly gone.
**Fix:** accept a *name*; the server owns the SQL text.

### A gate that cannot fail
**Symptom:** green forever, because the assertion was `>= 0` or the mutation was never added.
**Fix:** for every gate, add the mutation that must turn it red, and assert the refusal message names
the missing thing.

### A sample that rotted
**Symptom:** a documented example returns a refusal or the wrong metric after a rename.
**Fix:** run every sample in a gate: it must answer, or refuse *on purpose* (listed explicitly).

### Regenerating one profile's cached page into another
**Symptom:** the second profile serves the first profile's graph.
**Fix:** generated artifacts belong to the profile (`app_html`), not to the app.

### A settings file read by a subprocess that ignored the profile
**Symptom:** the parent shows one dataset, the child answers from another (same class names, wrong
tables: `:OrderLine declares no :physicalTable`).
**Fix:** one environment variable (`APP_SETTINGS`) honoured by every module, including children; and
no module may hard-code an ontology folder.

### An action file bound at import
**Symptom:** changing the profile's actions file has no effect.
**Fix:** resolve defaults at call time, not at function-definition time.
