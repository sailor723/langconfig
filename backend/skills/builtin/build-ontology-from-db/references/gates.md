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
| **profile isolation** | each profile loads its own ontology | a module hard-codes a folder |
| **i18n** | translation changes words, not markup or code | `<pre>`, `<code>`, `<script>` change |

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
