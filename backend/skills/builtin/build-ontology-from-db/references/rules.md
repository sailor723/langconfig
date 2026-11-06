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
