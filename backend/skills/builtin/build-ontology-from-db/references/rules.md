# The configuration rules

Twenty-eight rules (the count is checked by `scripts/check_skill.py`, which is how this line went stale at "Fifteen" while the file held nineteen). Each one exists because skipping it produced a wrong number, a silent empty page, or
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

**Gate:** `check_structure.py` — 类要有表与主键、属性要有本表列、无孤儿

## 2. A link is declared, never inferred

```ttl
:routeOf a owl:ObjectProperty ; rdfs:domain :Trip ; rdfs:range :Route ;
    :physicalColumn "route_id" ; :references :Route .
```

*If you skip it:* joins get built by column-name coincidence. `customer_id` on two tables "looks
like" a join, and one of the two is a different customer.

**Gate:** `check_structure.py` — 对象属性要有 `:references` 且目标类存在

## 3. Composite keys are joined on every column

```ttl
:productSupplier a owl:ObjectProperty ; rdfs:domain :OrderLine ; rdfs:range :ProductSupplier ;
    :physicalColumn "l_partkey, l_suppkey" ; :referencesKey "ps_partkey, ps_suppkey" ;
    :references :ProductSupplier .
```

*If you skip it:* the join matches every supplier of that part, and the cost metric silently
multiplies. (Measured: a 6-month supply cost inflated by ~2.4×.)

**Gate:** `check_structure.py` — 复合键按逗号拆开逐列校验

## 4. Every number is a declared metric

```ttl
:overloadRate a owl:DatatypeProperty ; rdfs:label "超载率" ;
    :numerator :overloadedTrips ; :denominator :trips .
```

*If you skip it:* the number lives in a dashboard query, then in a slide, then in a decision, and
nobody can say where it came from or change it once.

**Gate:** `check_ontology_generic.py --family C` — 每个数字必须是已声明指标

## 5. Meaning and computation are separate files

`02-meaning.ttl` says what a metric *is*; `metrics_ext.ttl` says how it *computes*
(`:aggregate`, `:grain`, `:universe`, `:where`, `:groupBy`).

*If you skip it:* you lose the measurement the split exists for — loading without the overlay must
**refuse** aggregates, because `:aggregate`/`:grain` are what a semantic layer was holding implicitly.

**Gate:** `check_ontology_generic.py --family C` — 含义/计算分层，`metrics_ext.ttl` 只放计算

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

**Gate:** `check_ontology_generic.py --family R` — 定义可编译且选出 >0 行

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

**Gate:** `check_ontology_generic.py --family R` — 谓词类必须自报理由

## 8. A ratio declares its two sides

`:numerator`/`:denominator`, each compiled as its own metric; `:scale` for a percentage.

*If you skip it:* `sum(a)/sum(b)` typed as a formula, and then `avg(a)/avg(b)` somewhere else, and the
two answers differ by a factor the business cannot see.

**Gate:** `check_ontology_generic.py --family C` — 比率必须写分子分母

## 9. Grain is mandatory for aggregates

`:grain` + `:universe`. A metric with a formula but no grain must be **refused by name** — "this is
what the semantic layer held implicitly".

*If you skip it:* silent double counting, because an aggregate over a joined set has no defined
universe.

**Gate:** `check_ontology_generic.py --family C` — 带 `:formula` 无 `:grain` 必须拒绝

## 10. A windowed definition needs a snapshot fact

"Driver quality over the last 30 days" has nothing in OWL to attach to. Materialise `driver_stats`
(window_days as part of its key) and define over that.

*If you skip it:* the definition is moved into SQL, and the window becomes a magic number in a report.

**Gate:** `check_ontology_generic.py --family G` — 窗口列必须存在且窗口只注入 big_tables

## 11. Name properties after the question

`:regionName` (`:physicalColumn "r_name"`), not `:r_name`. The local name is the word the question
matches; the column name is an implementation detail.

*If you skip it:* "revenue by region" cannot match `r_name`, and the NL layer refuses a question the
data can answer.

**Gate:** **Ungated (advisory)** — 命名是判断，不是可判定的规则

## 12. Aliases belong to a profile, not to the codebase

"region" means *the store's city* in one dataset and *a real object* in another. Declare aliases per
profile; never in the shared alias table.

*If you skip it:* you fix one dataset by breaking another — this happened, and a retail NL gate caught it.

**Gate:** `check_samples.py` — 别名丢失会让样例变红

## 13. Writes are declared actions on action-owned state

`:state "action"` marks the properties only an action may write; the action declares parameters,
preconditions, effect, permission and audit. The guard and the effect compile from the same axiom the
read path compiles.

*If you skip it:* writes become ad-hoc SQL, no audit trail survives, and an analytics user edits the
state a business process owns.

**Gate:** `check_actions.py` — 写动词要有编译过的前置条件与审计

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

**Gate:** `check_actions.py` — 写入只能走声明过的动作路径

## 14. Guardrails are part of the contract

`big_tables` with their time column, a page cap, a plan budget, a statement timeout — and one rule
that outranks the rest: **a declared metric is never windowed.** Listings may be narrowed (and say
so); metrics may not.

*If you skip it:* an unbounded scan on a table with tens of millions of rows takes the database down,
or — worse — a `now()`-relative window quietly returns zero rows and looks like a fact.

**Gate:** `check_guard.py` + `check_ontology_generic.py --family G` — 护栏是契约的一部分

## 15. Gate before page, and make the gate able to fail

Ground truth first (a different algebraic route), mutations second (drop `:references`, duplicate a
column, delete `:grain`, misspell a formula column), UI last. Every gate must have a mutation that
turns it red.

*If you skip it:* you ship confidence, not correctness. A gate that cannot fail is decoration.


---

**Gate:** **Ungated (MUST)** — 变异证据要写进 `steps.json`；门还没做（见 SKILL.md「本轮实测」）

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

**Gate:** **Ungated (MUST)** — 时间窗口/时间轴要在类上声明；门还没做

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

**Gate:** `check_ontology_generic.py --family C` + `check_samples.py` — 分组比率两侧必须同粒度

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

**Gate:** **Ungated (MUST)** — 时间序列要声明时间桶；门还没做

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

**Gate:** `check_dashboard.py` — 面板只能引用已声明指标，分组能加权回未分组


## 20. Every metric carries `:askedAs` — the menu is a declaration

A metric nobody can ask for does not exist for a user. `:askedAs` is the phrase the NL layer matches; a
label alone is a caption, not an entrance.

**Gate:** `check_ontology_generic.py --family C` (C5a: every metric declares it; C5c removes one and the
gate must go red). Measured when it was written: 0 of 43 metrics carried it while every gate stayed green.

## 21. Every `:businessDescription` names its source

`口径来自 answers:Q2` or `docx#Q10` or `refused: <which question is missing>`. A number with no source is
not a declaration, it is a guess that compiled.

**Gate:** `check_ontology_generic.py --family C` (C5b: every `:businessDescription` names `answers:` /
`docx#` / `doc#` / `refused:` / `measured:` / `table:`). Measured when it was written: 11 of 43 metrics had no
source, added after the ontology was already installed.

## 22. A publish is measured on the STAGED copy, not the installed one

`ontology_gates.py --key <key>` reads `profiles/<key>/` when a profile exists there — so "I staged, then the
suite was green" can describe the INSTALLED ontology. Record the staged id and its verdict
(`gates.json` → `pending_install`) and measure the staging tree itself.

**Gate:** **Ungated (MUST)** — the green was a coincidence, not a check.

## 23. Changing this skill is itself a gated change

Bump `version:`, run `scripts/check_skill.py` (this lint), push, then
`scripts/verify_skill_version.py --restage` so every agent's workspace copy matches the repo file.

**Gate:** `check_skill.py` — L1 version, L2 dead links, L3 reachability, L4 rules-vs-gates, L5 counts.

## 26. A metric with no reader does not ship, and no budget may be met by deleting the machinery

Two numbers decide whether a declaration set is honest, and neither is a gate:

* **Every metric has a reader** — a panel, a KPI card, a sample, the tutorial, or a `:numerator` /
  `:denominator` of a ratio. Measured on the v4 build: 149 metrics, 34 with no reader at all, every
  gate green.
* **A metric budget is spent on consumers, not on mechanics.** The `:numerator`/`:denominator` entries
  are what make a ratio compile — six KPI families need roughly fifty of them. Cutting a set to a
  budget (today ~60) therefore means trimming the tutorial, the samples, the panels and the cards,
  and saying which ones. Deleting the mechanics instead breaks `ratio_of_sums` and the next build
  re-adds them.

Removing a metric is a **consumer edit**, not a one-line delete: `tutorial.json`, `samples.json` and
`dashboard.json` all name metrics, and T2 ("every tutorial item is declared") is exactly the gate
that caught a trim which had not looked at the tutorial.

**Gate:** none — "does anything read this number" is a coverage question over five consumers (panels, KPI cards, samples, tutorial, ratio parts), and no gate counts them; the S7·5 self-check names
the four numbers, and a trim is re-gated by `--family T` (T2) plus `check_samples.py` and
`check_dashboard.py` for the consumers it touches.

**Ungated (advisory)**

## 25. Every KPI the material names reaches a panel, or the step is not done

A metric compiles, appears in the menu, answers correctly — and is still invisible, because nothing draws it. The
gate validates the panels that exist, so an ontology that declared six KPI families and shipped none of them can
be **entirely green**: measured on the v3 build, 36 KPI metrics from the customer's own KPI dictionary (准时 / 异常 /
超载 / 出勤 / 线路完成 / 违章 / 路权 / 油耗 / 维修 / TCO) landed with the board still showing v1's six panels.

**Gate:** none — this is a coverage check, so it must be written down where a person reads it: the publish note
lists one line per family, `family → metric → panel id → kind`. A family with no panel is absent on purpose, and
says why (no data / refused by name), never silently.

Corollary, learned the same afternoon: a **headline number belongs in `kpis` and in a panel**. The card answers
"what is it today"; the panel answers "where does it come from". Shipping only the card is how `tcoPerKm` and
`violationCount` became the two numbers nobody could interrogate.

## 24. Nothing a profile carries may name a machine

The line that must not exist: `NL_PYTHON = "/Users/weiping/.../.venv/bin/python"`. It made the Query page
work on the laptop it was written on and refuse on ECS with `nl.py failed: [Errno 2] No such file or
directory` — for every ontology, on the page people use most. The same class of bug sat in the actions
resolution: `PROFILE / actions_file` pointed retail's `actions.yml` at logistics and ABC, so their questions
died as `PromoteCustomer: :Customer has no :physicalTable` while retail stayed green.

The rule is about the deploy, not about tidy code: **a profile has to compile and answer on the machine that
serves it.** Every path a declaration or its runner uses is either derived from the install root
(`schema/actions.yml`, `ontology/`) or from an environment value (`${ONTOLOGY_DB_HOST:-127.0.0.1}`). An
origin-relative URL (`/api/...`) is the page's own address, not a file. A profile whose settings name
`/Users/...` or `C:\...` is a profile that has not been tested where it will run.

A **credential** is the same disease with a worse prognosis: it travels in git, it is in every clone, and
nothing else in this platform looks at it. Measured on `retail`, whose `settings.json` said
`"password": "postgres"` in plain text while every gate stayed green — and the gate that read that profile
printed the password back into its own output, which is the build report.

**Gate:** `check_ontology_generic.py --family X` — X1 scans the files a profile travels with and names every
machine path; X1b proves the scanner fails on a synthetic declaration (`/Users/someone/...`), so a green X1
means "looked and found nothing", not "looked at nothing". **X2** does the same for a literal password (the
allowed forms are `${VAR}`, `${VAR:-…}` and nothing), X2b proves that scanner fails on a synthetic
`"password": "hunter2"`, and the gate prints `password=<set>` rather than whatever the dsn holds.

## 27. A rebuild measures the database before it compares the documents

The first build enters at S0 and reads the database. A rebuild enters at S-1 and reads the documents — so a
database that grew is invisible to the one path that claims to be cheaper. Measured on a 2026-11-08 build
reviewed on 2026-11-11: its ledger said

    {"step": "S1", "why": "结构未变（无新增/删除对象与列）"}

while `check_structure` against the same database reported nine tables the ontology never modelled
(`driver_schedule, fuel_logs, incident_tickets, maintenance_orders, restriction_calendar, vehicle_axles,
vehicle_fixed_costs, violations, zone_permits`). It published anyway. "Structure unchanged" was an
assumption wearing the clothes of a measurement.

So S-1 opens with the gate, against the declarations that are installed:

    ontology_open(ontology_key="<key>", dest="work/<key>")          # a copy, never `cp -r` of the repo
    python backend/features/ontology/gates/check_structure.py --profile work/<key>/<key>_settings.json

Green → `skip: S1` is legal, and the entry carries the gate's last line (`NNN checks · 0 failed · green`) as its
evidence. Red → the database moved, not the document: S1 is not skippable, and the red line names the tables and
columns to add.

**Gate:** `check_structure.py` — 类→表/主键、属性→本表列、**每张表都被建模**、**每一列都可达**、无孤儿、无空类

*If you skip it:* the delta says "nothing changed" about a database that changed a lot, every later step is
built on that sentence, and the gate that would have caught it is the one nobody was told to run.

