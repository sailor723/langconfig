# The gates

A gate is a check that can **fail**, with a message that names what is missing. The matrix below is
what the three worked examples in `examples/` actually run; `scripts/check_ontology.py` is the
generic template.

| gate | protects | must go red when |
|---|---|---|
| **compile all** | every declared metric compiles, or refuses by name | a `:grain`/`:universe`/`:references` is missing |
| **ground truth** | the number is right | the compiled SQL disagrees with a second, hand-written query |
| **fan-out** | `count(DISTINCT pk)` where a join can duplicate | a naive `count(*)` over a joined set |
| **ambiguity** | one physical column on two joined classes | a duplicate column is added |
| **missing path** | joins only over declared edges | `:references` is dropped |
| **ratio shape** | numerator/denominator, never `sum/sum` typed | the ratio is rewritten as a formula |
| **cross-grain** | ratio of two metrics, divisor guarded | the denominator is not `NULLIF`-ed, or self-references |
| **composite keys** | both columns joined; tuple identity in counts | half the key is dropped |
| **grouped** | every requested dimension survives | a dimension is silently dropped |
| **window** | the facet boundary is inclusive; empty is `null` | the cutoff moves, or `0` is returned |
| **definitions** | axiom == hand SQL for the same class | the axiom's threshold changes |
| **declared predicate** | the one escape hatch reports itself | the note disappears, or an axiom + predicate coexist |
| **guard / cap** | `LIMIT` once, listings windowed, **metrics never** | a metric is windowed, or the cap doubles |
| **plan budget** | a huge scan is refused by name | the estimate is ignored (the config bug: it read the wrong settings) |
| **timeout** | every statement carries `statement_timeout` | `SET LOCAL` outside a transaction |
| **not-now-relative** | an empty injected window is reported | a historical dataset returns an empty page as a fact |
| **no free-form SQL** | the request never carries SQL | a route reads `payload["sql"]` |
| **samples** | every documented example still works | a metric is renamed; a sample rots |
| **tutorial steps** | `tutorial.json` names only declared objects/definitions/metrics | a step points at a metric that was renamed or dropped |
| **tutorial runs** | a metric step's number is produced by the compiled SQL, not typed | the metric refuses, or the number in the text drifts from the database |
| **tutorial teaches a refusal** | the refusal is part of what a reader learns | the tutorial only shows what works |
| **profile isolation** | each profile loads its own ontology | a module hard-codes a folder |
| **i18n** | translation changes words, not markup or code | `<pre>`, `<code>`, `<script>` change |

## The tutorial gate, concretely

`tutorial.json` is data, so its gates are structural — and they are run by the workbench, which is
the only thing that can resolve a name against the graph:

```bash
GET /api/tutorial/steps
# {ok:true, source:"profile", steps:[{kind,title,body,items}]}
#   -> source must be "profile" (not "derived"), and every items[] entry must exist

GET /api/tutorial/run?metric=collectionRate
# {ok:true, sql:"SELECT …", value:55.87, plan_rows:3236, ms:1, notes:[…]}
#   -> ok:false means the step teaches a metric that does not compile

GET /api/tutorial/definition?class=NoShowAppointment
# {ok:true, predicate:"status = 'no_show'", table:"appointments", rows:1077}
#   -> rows:0 means the definition selects nothing: a dead definition, not a tutorial step
```

The mutation that proves these gates bite: rename one metric in `metrics_ext.ttl` and re-ask — the
step must stop resolving, and `run` must refuse by name. A tutorial whose steps cannot go stale is
not being checked, it is being printed.

## How to make a gate bite

For each check, add the mutation that must break it, and assert the *refusal names the missing thing*:

```python
mut = copy.deepcopy(g)
mut.remove((None, P("references"), None))            # joins lose their declaration
assert_refused(compile_metric, mut, "premiumRevenue")  # and the message mentions :references

mut.add((P("tier_dup"), P("physicalColumn"), Literal("tier")))  # ambiguous column
assert_refused(compile_metric, mut, "premiumRevenue")

mut.remove((P(metric), P("grain"), None))            # no grain -> refuses the aggregate
```

Three rules that keep the suite honest:

1. **Every gate has a mutation.** If you cannot construct one, the check is decoration — rewrite it
   as a claim about a *value* (assert the number equals ground truth) or delete it.
2. **Refusals are matched by reason, not by effect.** Assert `":grain" in message`, not merely "it
   raised" — otherwise an unrelated crash passes as a refusal.
3. **Run every profile's gates together.** A change that fixes one dataset's words can break another's
   matching; the suite is the only place that shows it.

## Order of adoption

Do not write gates breadth-first. Add them in this order, because each one makes the next cheaper:

1. `compile all` — the shape is right before anything is measured
2. `ground truth` on 2–3 metrics — the numbers mean what the business says
3. mutations for those metrics — the checks above actually bite
4. `composite` / `grouped` / `window` — only for the structures that dataset has
5. `guard` + `plan budget` — once there is a big table
6. `samples` and the language layer — last, because their content depends on the names
7. `i18n`, `profile isolation` — when a second profile exists

## The publish gate (phase 11)

The last gate is not a script you run — it is the channel you hand the artifacts to.
`ontology_publish` re-runs this entire suite against a **staging copy of the installed ontology** and
compares its refusals with the ones already there:

- **new refusal → refused publish.** A metric that stops compiling is a number that silently
  disappears from a report; the publish must not be installable.
- **carried refusal → published.** Things the installed ontology already refused are the existing
  backlog, not this change's fault. Dressing them up as new failures makes the gate unusable, and
  treating them as success is how a definition rots.
- **NOT RUN gates are printed by name** in the same report. A reader must be able to tell "this
  profile has no truth map" from "every number was verified".

If the tool is absent, the gate is NOT RUN: say so, hand over the folder, and do not write into the
installed ontology by hand.

### Samples: a count is never answered by a class

A sample question that asks for a **number** must be answered by a metric or refused by name —
never by a listing of a class. This is the failure that looks most like success:

```
Q: 高风险线路数        -> ANSWERED with a listing of :Route      (wrong: no such metric)
A: REFUSED: asks for a number (数), the best declaration is the CLASS :Route —
   no metric declares that count. Declare a metric on :Route with :aggregate and :grain.
```

Two cases, both gated (`check_nl.py` N13):

- **declared count** → the metric: `订单数` / `有多少订单` / `how many orders` → `orderCount`;
- **undeclared count** → refusal naming the class and what to declare. `线路有哪些` (a list
  request) still answers with the class — the rule must not eat honest reads.

The gate is worth having because Chinese tokenises to whole runs and 2-grams: `订单行`
(order lines) contains `订单` (orders), so the class `:Order` swallows the sentence and a
count of order orders gets answered with a count of orders. A noun keeps its modifier in
**front**, so a suffix match counts and a prefix-only match does not.

Two related traps measured in the same session:

- `sqlgen._apply_env_profile()` resolved a profile's `ontology_dir` against `retail_graph/`
  rather than the profile's own folder, so a profile outside that folder loaded an **empty
  graph** — every NL question refused with `metrics []`, which reads exactly like "this
  ontology declares nothing".
- a gate that compares a `now()`-relative window against a **constant** rots: `969.5` had
  silently drifted to a correct `849.5`. Compare against an independent route instead.

## Two gates about the NL layer (both run per profile)

A built ontology is judged by the questions it answers, so the matcher is gated like the compiler:

- **N1 — a declaration's own label is final.** For every CJK label, 「<label>是多少」 must resolve to
  that declaration. Measured failure: 「每千公里破损箱数是多少」 was refused although
  `:damagePer1kKm` carries exactly that label — an alias token (破损→damaged) had no counterpart in
  the metric's own words, so the salient-noun veto discarded a literal label.
- **N2 — a superlative is a number.** 「哪台车破损最多」 must reach a metric or be refused by name;
  a class listing ("here are the damaged stops") is the one outcome that fails.

Both live in `check_ontology_generic.py`, so every profile gets them:
23/23 labels on logistics, 28/28 on clinic.

Two "gates" that are really habits, because each one silently rots:

- **do not compare a `now()`-relative number to a constant** (the data ages; the gate starts failing on
  a correct answer — compare to an independent route);
- **run metrics with `mode="declared"`** (the default mode windows a big table and answered 3950 where
  the definition says 4050).
