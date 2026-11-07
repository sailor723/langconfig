---
name: build-ontology-from-db
description: Use when asked to build an ontology (or semantic layer, or "compile metrics from a database") on top of an existing PostgreSQL database — walks the decision order that keeps numbers honest (objects and grain first, meanings as axioms, computation as an overlay, guardrails, gates before UI) and refuses to guess what only the business can decide
tags: [ontology, semantic-layer, postgres, metrics, data-modeling, sql]
triggers:
  - When asked to build or extend an ontology / semantic layer for a database
  - When a KPI or metric must be defined once and compiled, not hand-written per report
  - When "the same metric gives two different numbers" and the definitions must be settled
version: 1.0
author: weiping
---

# Building an ontology from a database

The goal is not a schema diagram. It is a set of **declarations** from which every number is
*compiled*: change the ontology and the number moves; change nothing and no report can drift.
An ontology that cannot refuse is a dashboard with extra steps.

This skill is the order of decisions plus the checks that keep them honest. It is deliberately
slow at exactly two points — the model sketch and the definitions — because those are business
decisions, not modelling ones.

**Read [references/rules.md](references/rules.md) before writing TTL.** It lists the fifteen
configuration rules with the failure each one prevents. [references/pitfalls.md](references/pitfalls.md)
is the catalogue of failures observed in real builds — read it after the first draft, it will
explain most of what goes wrong. [references/tuning-log.md](references/tuning-log.md) is the same
thing for the *agent's own behaviour*: 14 measured failures (reading the engine instead of asking it,
answering a count with a class listing, loading an empty graph without noticing, a gate that compared
a moving number to a constant) with the rule and the gate each one became. [references/gates.md](references/gates.md) is the gate matrix and
how to prove each gate bites.

## The two stop-and-ask points

1. **After the model sketch (phase 0).** Objects, grain, volumes, the questions, the decisions,
   whether anything is written, and whether "last N days" is meaningful in this data. Show it to
   the human before writing any TTL. Do not proceed on assumptions — a wrong grain costs a rebuild.
2. **At the definitions (phase 4).** What does this number *mean*, in the business's words? Which
   set of rows is in scope, at what grain, with which threshold? Write down the answers as axioms;
   do not invent a threshold, a grain, or a "good route" definition.

Everything else is autonomous, and ends with a table the human can argue with.

## The phases

### 0. Read the brief

From whatever the human gave you (prose, slides, a call), extract and write down:

- **objects** and their **grain** — what is one row of the biggest table, and roughly how many
- **the questions** a user would type, verbatim, in their own words
- **the decisions** the numbers support ("should we do X?") — these select the real metrics
- **writes** — does anything change data, and would it need an audit trail?
- **time** — is "last 30 days" meaningful, or are periods named (FY24, Q3, 2025)? This decides the
  guardrail profile later (phase 6), and it is the single most common silent bug.

Output: a one-page sketch. Get it confirmed.

### 1. Introspect the database

```
python scripts/introspect_db.py --dsn "host=… port=… dbname=… user=…" --out brief.json --sample-nulls
```

The brief answers the questions the configuration must answer: primary keys (**including
composite**), foreign keys (**including composite**), row counts, date columns with their real
`min`/`max`, the cardinality of candidate dimensions, and NULL counts on candidates for
definitions. Read the `shape_hint` for each table — and treat every `CONFIRM` as a question for the
human, not an answer.

The script runs `ANALYZE` when the database has no statistics yet (`reltuples = -1` on a freshly
loaded database), because "unknown rows" is the one answer that makes the guardrail decisions
impossible.

### 2. Classify every table

| shape | becomes | how you know |
|---|---|---|
| a thing with identity | **object** (class with `:physicalTable`/`:primaryKey`) | own key, described in the business's nouns |
| many orders → one customer | **link on the child row** (FK column + `:references`) | one FK, no payload |
| many-to-many, no payload | a junction: keep it a class only if it must be listed | PK = the two FKs |
| many-to-many **with payload** | **reified class** — the link carries data (`qty`), so it needs a row of its own | two FKs + payload columns |
| a windowed fact ("last 30 days per driver") | **snapshot table** — a window is not a column, a definition needs a row to attach to | the question names a period |

Write the classification down. Every table either gets a shape or an explicit "deferred, because…".
Note the target/model cost of reification in the sketch: the link becomes a grain you can group by,
and a wrong join will fan out rows.

### 3. Write `01-structure.ttl`

```
python scripts/scaffold_ttl.py --brief brief.json --ns https://example.org/onto# --out 01-structure.ttl
```

The draft is mechanical (class per table, property per column, link per FK, composite keys handled).
Two things it now gets right for you, because they are easy to get wrong by hand:

- **property names are unique per class** (`:patientId`, `:appointmentId`): in RDF the same local
  name is ONE property, so `:id` on six classes becomes a property with six domains and the compiler
  then refuses it as ambiguous everywhere.
- **an FK column becomes the link, not also a data property**: declaring it twice makes one
  relationship two things, and the name collides with the target's own key column.
Then **fix what only a human can**:

- **name every property after the question, not the column.** `r_name` becomes `:regionName`
  (`:physicalColumn "r_name"`), because "revenue by region" must match it. The draft marks the ones
  it could not name.
- mark the properties a write owns with `:state "action"` — never by guesswork; ask.
- delete the objects you deferred, and add `:businessDescription` where the meaning is not obvious
  from the name. That description is what a reviewer reads; it is not decoration.
- label the columns that make a definition possible (the boolean/enum a definition will restrict on).

### 4. Write `02-meaning.ttl` — the definitions

For each of the 6–10 metrics in the sketch, ask "what does this MEAN", then declare it:

```ttl
# a single criterion: a facet on the object's own column
:LateStop owl:equivalentClass [ owl:intersectionOf ( :Stop
    [ a owl:Restriction ; owl:onProperty :on_time ; owl:hasValue false ] ) ] .

# several criteria AND-ed: intersection
# several criteria OR-ed: owl:unionOf  (compiles to (a OR b OR c))
# a code rather than a number: owl:hasValue
# a comparison between two columns, or IS NULL: :physicalPredicate — the ONE escape hatch,
#   and it must say so in a comment; a class with both an axiom and a declared predicate is refused
```

Metrics declare *meaning*, not computation:

```ttl
:overloadRate a owl:DatatypeProperty ; rdfs:label "超载率" ;
    :numerator :overloadedTrips ; :denominator :trips .     # a ratio of two declared metrics
:damagedBoxes a owl:DatatypeProperty ; :aggregate "sum" ; :grain :Stop ; :universe :Stop ;
    :formula "damaged_boxes" .                              # a per-row formula, aggregated
```

Rules that keep it honest: the threshold lives **once**; a ratio declares numerator/denominator
(never `sum(a)/sum(b)` typed by hand); `:scale` for a percentage; `:groupBy` for a dimension; a
windowed metric declares the window in the axiom (`:where :RecentOrder`) rather than in SQL.

### 5. Write `metrics_ext.ttl` — the computation overlay

Meaning and computation are separate files on purpose. `metrics_ext.ttl` holds `:aggregate`,
`:grain`, `:universe`, `:where`, `:groupBy`, `:numerator`/`:denominator`/`:scale`. A metric with a
`:formula` but no `:grain` **must refuse** — that refusal is the measurement of what a semantic layer
was holding implicitly.

### 6. Compile, then verify against a second, hand-written route

```
python scripts/check_ontology.py --profile profile.json --truth truth.json
```

`truth.json` is `{metric: number}`, written **by hand, with a different algebraic route** (e.g.
`sum(price) - sum(price*discount)` for the metric compiled as `sum(price*(1-discount))`). If the two
agree, believe it; if the compiler merely returns something, do not. Write the truth numbers into the
ontology's `:businessDescription` too, so a future reader sees the expected value next to the
definition.

Then let the mutations argue: drop a `:references`, duplicate a column, delete `:grain`, misspell a
formula column — each must go red. **A gate that cannot fail is decoration.**

Two things that make a gate decay instead of fail, both measured: comparing a `now()`-relative number
to a constant (the demo data ages and the gate starts "failing" on a correct answer — compare against
an independent route instead), and running a metric with the guard's default mode (it windows a big
table and answers 3950 where the definition says 4050 — a declared metric is never windowed; use
`mode="declared"`).

### 7. Guardrails — decide refuse-vs-narrow for this data

Read the `date_range` from the brief before choosing anything:

- data is **recent** → a now-relative window is meaningful: `default_window_days: 30/90`, and
  listings get the window while metrics are never windowed.
- data is **historical** (a year old or more, synthetic, or clearly bounded) → **refuse** instead of
  narrowing (`default_window_days: 0`), because a `now()`-relative window silently returns nothing.
- always: page cap (`max_rows`), plan budget (`max_plan_rows`), statement timeout, and
  `big_tables` for the largest tables with their time column.

A **declared metric must never be windowed** by the guard: that changes the number its definition
promises. Metrics report the unbounded scan and the plan budget decides.

### 8. Menu, names, samples — then the pages

- every metric gets a `rdfs:label` in the user's language and a name a question can match
- per-profile aliases for words that mean different things per dataset (in one dataset "region" is
  a city; in another it is a real object)
- **samples**: 8–15 questions, one per capability, at least one that must be refused. Then gate them
  — every sample must answer, or refuse *by name* — because a rotted sample is worse than none.
  Write `samples.json` next to the profile with what each question must produce (`value`, `rows`, or
  `refused_by_name`), the numbers coming from a **second SQL route**; mark what the ontology cannot
  honour yet as `unresolved` with the missing declaration named. `retail_graph/check_samples.py
  --profile …` runs it, and the generic gate runs it as `S` on every publish.
- only then the UI/profile/tabs. The profile is one file: namespace, ontology dir, overlay,
  generated page, DSN, feature flags, guardrails, samples, aliases, actions file.

### 9. Write the tutorial — an ontology nobody can read is a database with extra steps

Every ontology ships a tutorial. The workbench **derives** one from the declarations when none is
authored (objects → definitions → metrics → refusals → guardrails), so this phase is not about
producing *a* tutorial; it is about producing one that teaches **this** ontology's decisions,
in the user's words, with numbers that are actually run.

Write `tutorial.json` **next to the profile**:

```json
{"title": "Clinic ontology",
 "intro": "One sentence: what this ontology is for and what it refuses to guess.",
 "steps": [
   {"kind": "objects", "title": "…", "body": "…", "items": ["Appointment", "Patient", "Invoice"]},
   {"kind": "definitions", "title": "…", "body": "…", "items": ["NoShowAppointment", "DecidedClaim"]},
   {"kind": "metrics", "title": "…", "body": "…", "items": ["collectionRate", "lineRevenue"]},
   {"kind": "refusals", "title": "…", "body": "…", "items": ["claimDecisionDays"]},
   {"kind": "guard", "title": "…", "body": "…", "items": []}
 ]}
```

Rules that keep it honest:

- **every `items` name must be declared** — an object, a definition class or a metric that
  `GET /api/tutorial/steps` and the graph both know. A typo is a step that teaches nothing.
- **at least one metric step must actually run**: the workbench executes it through
  `GET /api/tutorial/run?metric=…` under the guardrails, so never write the number into the text —
  the step shows the number the database returns. Same for a definition: `…/definition?class=…`
  reports the predicate and the row count.
- **at least one refusal step.** The refusal is the most valuable thing you are shipping; a
  tutorial that only shows what works teaches the wrong lesson.
- **6–10 steps, ordered by the reader's question**, not by your file layout. Start where the user
  starts ("what is one row here?"), not with the overlay.
- write it in **the user's language**, in the business's words — the tutorial is the one artifact in
  this build that is read by someone who will never open the TTL.
- the `guard` step carries no `items`; the workbench renders the profile's limits itself.

Verify before you claim done:

```
GET /api/tutorial/steps            -> "source": "profile", every item present
GET /api/tutorial/run?metric=<one of your metric steps>   -> ok:true, a value, plan_rows
GET /api/tutorial/definition?class=<one of your definition steps> -> ok:true, rows > 0
```

### 10. Deliver the refusals

The most valuable artifact is the list of what the ontology **cannot** answer and why:

```
REFUSED  lateLineRevenue: :LateLine has no owl:equivalentClass axiom
REFUSED  revenue by store: nothing declares a grouping by ['store']
REFUSED  price by brand: :Price declares no :grain — an aggregate needs the object grain
```

That list is the backlog and the negotiation with the business. Ship it with the numbers.

### 11. Publish through the channel — the ontology lands itself

The artifacts are not the deliverable until they are *installed*. Call the `ontology_publish` tool
with your workspace's ontology folder instead of copying files into the repo by hand:

```
ontology_publish(ontology_key="logistics",
                 source_dir="ontologies/logistics",   # 01-structure.ttl, 02-meaning.ttl,
                                                      # metrics_ext.ttl, *_settings.json, tutorial.json
                 note="added damagedBoxes; 3 refusals carried")
```

What it does, and what it refuses to do:

- It copies your files over a **staging copy of the installed ontology** and re-runs the whole suite
  there: every metric compiled or refused **by name**, every gate. You get that report back.
- A publish that introduces a **new refusal** or a **failing gate** is refused at stage time. Carried
  refusals (already refused before you started) are listed separately — those are not yours.
- It **never installs**. A human with the `ontology_editor` role confirms the apply in one click
  (Settings → Ontology → pending publishes); that re-runs the gates on the installed path, commits
  with the gate summary, and reloads the workbench.

So the honest end state of a build is: **files written, gates green where they can run, staged, and a
named report of what a human must decide.** Never leave the artifacts only on your disk, and never
claim the ontology is live because a publish was staged.

## What this skill will not do

- invent a threshold, a grain, a dimension, or an "acceptable" rate — ask
- write a number into SQL, a report, or a test
- accept SQL from a caller (the compiler is the only source of SQL)
- claim a metric is right because it ran — ground truth is a second, independent query
- ship a profile without its gates, or a gate that cannot go red
- treat a refusal as a failure: refusals are the contract

## Requirements (provided by the agent, not by this skill)

| capability | why |
|---|---|
| **shell execution** (`execute` / `bash`) | the three scripts under `scripts/` are the phases: introspection, scaffolding, gating |
| **file read + write** | the skill's `references/` and `examples/` are read on demand; the TTL it produces is written to disk |
| **a PostgreSQL connection** | introspection and every gate run against the real database, never a description of it |
| **the workbench (or any host that serves the ontology)** | phase 9's tutorial is *verified by running it*; without a host, write the file and say the verification is NOT RUN |
| **a Python environment with `psycopg2` + `rdflib`** | the scripts import them; the repo's `backend/.venv` already has psycopg2, and `rdflib` only matters for the gate |
| **the `ontology_publish` tool** | phase 11: the build lands through the validated channel. Without it, hand the folder over and say the publish is NOT RUN — do not copy files into the ontology repo |

The compiler and guardrails (`sqlgen.py`, `guard.py`) live in the host repo. If they are absent, the
skill still produces the TTL and the definitions; the **gate** is what needs them.

## Not this skill's job

| hands off to | why |
|---|---|
| **the host app's UI** (profiles, tabs, tutorial pages) | the skill stops at ontology + profile + gates; presentation is a separate concern |
| **writing to the database** (actions, audit) | that is a declared-action concern with its own review; the skill only marks which properties a write may own (`:state "action"`) and asks |
| **deciding a threshold, a grain, or a business rule** | those are the two stop-and-ask points; guessing them is the failure the skill exists to prevent |
| **R2RML / OBDA mappings** for a SPARQL lane | a different mapping discipline, and it needs its own gate |

## Working with the human

Ask, in this order: (1) the sketch, (2) the definitions, (3) the refusals. Show real numbers from
the real database each time, and say plainly which numbers are *unverified* if any are. When you find
a bug in your own compiler or gate while building, fix it and say so — the bug is evidence, not
embarrassment.
