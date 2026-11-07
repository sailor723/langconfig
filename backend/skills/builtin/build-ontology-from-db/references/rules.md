# The configuration rules

Fifteen rules. Each one exists because skipping it produced a wrong number, a silent empty page, or
a claim nobody could defend. The "if you skip it" line is what actually happened, not a warning.

## 1. An object is not a table

A class declares `:physicalTable` and `:primaryKey`; a property declares `rdfs:domain` and
`:physicalColumn`. The table is where the object is stored — the object is the thing with identity
and properties.

```ttl
:Vehicle a owl:Class ; rdfs:label "车辆" ; :physicalTable "vehicles" ; :primaryKey "id" .
:plate   a owl:DatatypeProperty ; rdfs:domain :Vehicle ; :physicalColumn "plate" .
```

*If you skip it:* the report becomes "columns and tables", and the business review turns into a
schema review — the questions stop being answerable in their own words.

## 2. A link is declared, never inferred

```ttl
:routeOf a owl:ObjectProperty ; rdfs:domain :Trip ; rdfs:range :Route ;
    :physicalColumn "route_id" ; :references :Route .
```

*If you skip it:* joins get built by column-name coincidence. `customer_id` on two tables "looks
like" a join, and one of the two is a different customer.

## 3. Composite keys are joined on every column

```ttl
:productSupplier a owl:ObjectProperty ; rdfs:domain :OrderLine ; rdfs:range :ProductSupplier ;
    :physicalColumn "l_partkey, l_suppkey" ; :referencesKey "ps_partkey, ps_suppkey" ;
    :references :ProductSupplier .
```

*If you skip it:* the join matches every supplier of that part, and the cost metric silently
multiplies. (Measured: a 6-month supply cost inflated by ~2.4×.)

## 4. Every number is a declared metric

```ttl
:overloadRate a owl:DatatypeProperty ; rdfs:label "超载率" ;
    :numerator :overloadedTrips ; :denominator :trips .
```

*If you skip it:* the number lives in a dashboard query, then in a slide, then in a decision, and
nobody can say where it came from or change it once.

## 5. Meaning and computation are separate files

`02-meaning.ttl` says what a metric *is*; `metrics_ext.ttl` says how it *computes*
(`:aggregate`, `:grain`, `:universe`, `:where`, `:groupBy`).

*If you skip it:* you lose the measurement the split exists for — loading without the overlay must
**refuse** aggregates, because `:aggregate`/`:grain` are what a semantic layer was holding implicitly.

## 6. A definition is an axiom (AND / OR / code)

```ttl
:LateStop    owl:equivalentClass [ owl:intersectionOf ( :Stop [ a owl:Restriction ;
                 owl:onProperty :on_time ; owl:hasValue false ] ) ] .
:Failed      owl:equivalentClass [ owl:unionOf ( :LateStop :TempExcursion :DamagedStop ) ] .
:AtRisk      owl:equivalentClass [ owl:unionOf ( [a owl:Restriction ; owl:onProperty :on_time_rate ;
                 owl:withRestrictions ( [xsd:maxInclusive 0.93] ) ] … ) ] .
```

*If you skip it:* "failed" becomes four hand-written `WHERE` clauses that drift apart. Every report
has its own version of the definition.

## 7. One escape hatch, and it reports itself

OWL cannot compare two columns, nor express `IS NULL`:

```ttl
:OverloadedTrip :physicalPredicate "load_boxes >= box_capacity_snapshot OR …" .
```

It compiles, and the compiler returns a note saying the definition is **declared, not derived**. A
class with *both* an axiom and a declared predicate is refused (the declared one would silently
replace the compiled one).

*If you skip it:* either the definition is missing, or hand-written predicates become the norm and
the ontology is documentation for SQL nobody compiles.

## 8. A ratio declares its two sides

`:numerator`/`:denominator`, each compiled as its own metric; `:scale` for a percentage.

*If you skip it:* `sum(a)/sum(b)` typed as a formula, and then `avg(a)/avg(b)` somewhere else, and the
two answers differ by a factor the business cannot see.

## 9. Grain is mandatory for aggregates

`:grain` + `:universe`. A metric with a formula but no grain must be **refused by name** — "this is
what the semantic layer held implicitly".

*If you skip it:* silent double counting, because an aggregate over a joined set has no defined
universe.

## 10. A windowed definition needs a snapshot fact

"Driver quality over the last 30 days" has nothing in OWL to attach to. Materialise `driver_stats`
(window_days as part of its key) and define over that.

*If you skip it:* the definition is moved into SQL, and the window becomes a magic number in a report.

## 11. Name properties after the question

`:regionName` (`:physicalColumn "r_name"`), not `:r_name`. The local name is the word the question
matches; the column name is an implementation detail.

*If you skip it:* "revenue by region" cannot match `r_name`, and the NL layer refuses a question the
data can answer.

## 12. Aliases belong to a profile, not to the codebase

"region" means *the store's city* in one dataset and *a real object* in another. Declare aliases per
profile; never in the shared alias table.

*If you skip it:* you fix one dataset by breaking another — this happened, and a retail NL gate caught it.

## 13. Writes are declared actions on action-owned state

`:state "action"` marks the properties only an action may write; the action declares parameters,
preconditions, effect, permission and audit. The guard and the effect compile from the same axiom the
read path compiles.

*If you skip it:* writes become ad-hoc SQL, no audit trail survives, and an analytics user edits the
state a business process owns.

## 13b. A write path is a declaration, and it is the only way state changes

Measured on the logistics decision log (`dispatch_decisions`, 2026-11), which exists for one reason:
`trips` records the OUTCOME of a dispatch decision and never the decision, so "did the good drivers get
the bad routes" is untestable — `corr(准时率, 趟数) ≈ 0` is what you can measure, and it is not an answer.

```yaml
- name: RecordDispatchDecision
  applies_to: DispatchDecision
  parameters:
    trip_id: { type: integer, required: true }      # …
  preconditions:
    - { kind: exists, object_type: Trip, key: "{trip_id}" }
  effect:
    create: DispatchDecision
    values:
      decidedTripOf: "{trip_id}"                    # an ObjectProperty: a FK is a column
      loanPressureAtDispatch: "{loan_pressure}"
  permission: write:dispatch.decision
  audit: required
```

Three things that had to be true, each measured:

- **an effect may name a foreign key.** `effect_property` accepted only `owl:DatatypeProperty`, so writing
  `trip_id` forced a second declaration of the FK as a datatype property — which the structure file
  forbids (a FK column appears exactly once, on the ObjectProperty). Reading and writing now resolve the
  SAME declaration; `:state "action"` is still the only thing that admits a write.
- **`audit: required` is the floor**, and the audit row is written INSIDE the transaction: a refusal or an
  exception rolls back both the effect and its audit row. A write you cannot trace is not a governed write.
- **"has a decision" is a read, and it is an axiom, not SQL.** `:TripWithDecision` is
  `∃:decisionsOf.(:DispatchDecision)` with `:decisionsOf owl:inverseOf :decidedTripOf` — the compiler
  already emits `EXISTS (…)` for `owl:someValuesFrom`, so the coverage metric needed a declaration, not a
  new compiler feature. The inverse is declared because the FK lives on the OTHER table; a FK column name
  is never guessed.

The honest end state: the write path exists, is audited, and the metric reads `0 / 4,050` — because
nothing dispatches through it yet. **0 is a measurement, not a placeholder.**

## 14. Guardrails are part of the contract

`big_tables` with their time column, a page cap, a plan budget, a statement timeout — and one rule
that outranks the rest: **a declared metric is never windowed.** Listings may be narrowed (and say
so); metrics may not.

*If you skip it:* an unbounded scan on a table with tens of millions of rows takes the database down,
or — worse — a `now()`-relative window quietly returns zero rows and looks like a fact.

## 15. Gate before page, and make the gate able to fail

Ground truth first (a different algebraic route), mutations second (drop `:references`, duplicate a
column, delete `:grain`, misspell a formula column), UI last. Every gate must have a mutation that
turns it red.

*If you skip it:* you ship confidence, not correctness. A gate that cannot fail is decoration.


---

## 16. A time window filters the object's own time column — declare it on the class

`guard.default_window_days` decides whether a *listing* may be narrowed by `now()`. A **question's** time
window ("上个月", "最近 90 天") is different: it is a constraint the user stated, it must reach the SQL, and
it must be refused if it cannot.

Two declarations make that work, and both are per ontology:

```ttl
:Trip a owl:Class ; :physicalTable "trips" ; :primaryKey "id" ;
    :timeColumn "trip_date" ;            # the column a window filters on, for THIS object
    ...
:tripCount a owl:DatatypeProperty ; :supportsSlot :TimeWindow ; ...   # this metric accepts a window
```

Three rules learned the hard way (all measured):

- **the column belongs to the object, not to the slot.** A slot declaring `:filterColumn "placed_at"` is a
  retail-shaped assumption; in logistics it produced `column "placed_at" does not exist` for every metric
  that declared the slot. `:timeColumn` on the grain class removes the assumption.
- **declare the slot only where the column is the grain's own.** Pushing `WHERE trips.trip_date` onto a
  query whose FROM is `stops` fails with `column "trip_date" does not exist`: a window through another
  table needs a JOIN, and a compiler that adds joins by string surgery is a compiler that silently changes
  numbers. A metric whose grain has no own time column **refuses by name**, and the refusal names the
  nearest declared column one hop away — that is the backlog item, in the answer.
- **never declare the slot on a ratio** (`ratio_of_sums`): the filter would have to go into both
  subqueries, which is not implemented, so a windowed ratio is refused rather than answered half-windowed.

Gate `W1/W2` (`check_ontology_generic`): every metric that declares `:supportsSlot :TimeWindow` must have a
pushable `:timeColumn` on its grain, and asking a windowed question must put that column in the WHERE with
a value that is a subset of the all-time one — compared as `windowed <= all-time`, never against a
constant, because a `now()`-relative number rots.

## 17. A rate per group needs both sides at the same grain

`ratio_of_sums` + `:groupBy` used to be refused outright, which made every "per vehicle / per route"
RATE undeclarable — and a dashboard's whole question is *per what*. It compiles now, under one rule:

```ttl
:damagePer1kStopsByVehicle a owl:DatatypeProperty ;
    :grain :Stop ; :universe :Stop ; :aggregate "ratio_of_sums" ;
    :numerator :damagedBoxCount ; :denominator :stopCount ; :scale "1000.0" ;
    :groupBy :plate ; :unit "count" .
```

```sql
SELECT vehicles.plate AS key1,
       (1000.0) * (((sum(stops.damaged_boxes))::numeric) / NULLIF((count(DISTINCT stops.id)), 0))
FROM stops JOIN trips ON stops.trip_id = trips.id JOIN vehicles ON trips.vehicle_id = vehicles.id
GROUP BY vehicles.plate ORDER BY 2 DESC;
```

- **same grain only.** A group's rate is "numerator summed inside the group ÷ denominator summed inside
  the group"; that is a number only when both sides are counted at the grain being grouped. A cross-grain
  ratio (`complaintsPer1kKm`: complaints at `:Complaint`, km at `:Trip`) has no per-group denominator that
  is not a choice, so it **refuses by name and says which grains disagree**.
- **the predicate may be `:concept` or `:where`, and the compiler reads both.** `:onTimeStops` carries
  `:concept :OnTimeStop` and `:overloadedTrips` carries `:where :OverloadedTrip`; a grouped-ratio path that
  read only `:where` compiled `count()/count()` = **100%** on-time — a silent wrong number, not a refusal.
- **never take the average of group rates.** Weighted reconstruction is the check:
  `Σ(rate × count) / Σcount` must equal the ungrouped rate. Gate `D3` does exactly that (measured:
  per-vehicle damage weights back to 159.03 = the fleet value; wrong pairs, zipped by row position
  instead of by key, "found" a 45.5% overload rate against the real 36.8%).

## 18. A time series declares its bucket — it never guesses one

`:timeBucket "day|week|month|quarter"` turns the grain's **own** `:timeColumn` into the first GROUP BY key
and orders the result ascending:

```ttl
:overloadRateByWeek a owl:DatatypeProperty ;
    :grain :Trip ; :universe :Trip ; :aggregate "ratio_of_sums" ;
    :numerator :overloadedTrips ; :denominator :tripCount ;
    :timeBucket "week" ; :unit "ratio" .
```

- **own column only**, same rule as the TimeWindow slot (rule 16): `:Stop` has no `:timeColumn`, so
  `:damagePer1kStopsByWeek` refuses and names `:Trip.trip_date` one hop away. Bucketing through a join is
  the compiler adding a join by string surgery — how a number goes quietly wrong.
- **ordered by the axis, not by the value.** A grouped metric orders `DESC` by its value; a series that
  keeps that order is not a series. The bucket is key 1, `ORDER BY 1 ASC`.
- **a word the compiler does not emit is refused**, not passed to `date_trunc` (`"weeks"` would compile and
  then fail at run time).
- **compiles ≠ readable.** `complaintCountByWeek` is correct and returns ONE row: all 6,876 complaints are
  stamped `2026-11-05 09:00`. Declare it anyway — the single bucket *is* the finding, and the dashboard
  panel says so instead of drawing a trend.

## 19. A dashboard is a declaration, and its holes are part of it

`<profile dir>/dashboard.json` says which DECLARED metric each panel shows, by what it is cut, which event
markers belong on it, and — for metrics that cannot answer — the refusal it expects. It contains no SQL and
no numbers. `retail_graph/run_dashboard.py` compiles/guards/runs it; `retail_graph/check_dashboard.py`
(D0–D6) makes it bite:

- `D0` every referenced metric is declared — or is listed under `holes` and really refuses;
- `D1` each panel's metric has the shape the panel needs (kpi = 1 row, matrix = 2 keys, ranked keys all
  have their `size_by`, a one-row series must declare why it has one row);
- `D2` a panel asking for the LOW end must declare `client_sort` — the compiler always emits `DESC`, so
  "the 20 worst vehicles" otherwise renders the 20 best;
- `D3` grouped numbers reproduce ungrouped ones (sums and weighted rates, keyed — never zipped by position);
- `D4` a declared hole that starts answering fails the gate (a stale declaration lies in both directions);
- `D5` independent SQL, written in the gate, agrees with the compiled numbers;
- `D6` an event marker names a metric with a time axis and has buckets on both sides of its date.

A panel that cannot answer is rendered as a refusal naming the missing declaration. That is the point:
a dashboard which silently drops a block is how a business mistake survives a year of review.
