---
name: edit-ontology-metrics
description: Use when asked to change an ontology that already exists — add or fix a metric, change what a number means, rename a property, adjust the guard profile or the samples — rather than build one from a database. Opens a copy of the installed ontology, edits the one file that owns the change, verifies the number against a second SQL route, and hands it back through the publish channel (stage only; a human applies).
tags: [ontology, semantic-layer, metrics, edit, gates, publish]
triggers:
  - When asked to add, change, fix or remove a metric in an existing ontology
  - When "this number is wrong / missing / not what we meant" and an ontology defines it
  - When a question should be answerable but the compiler refuses it
  - When relabelling, aliasing or re-teaching an ontology (labels, samples, tutorial)
version: 1.0
author: weiping

params:
  ontology_key:
    label: 本体
    description: the ontology this agent edits (the folder under features/ontology/profiles/)
    required: true
  repo:
    label: 本体仓库
    description: optional — where a learning MIRROR of the ontology lives. Unset means this app's own
      feature (backend/features/ontology), which is where the compiler, the gates and the profiles are.
    required: false
    default: ""
---

# Editing an ontology that already exists

An edit is not "write the SQL for it". An ontology's numbers are *compiled* from declarations, so
the whole job is: find the declaration that owns the number, change **that**, and prove the number
it produces. Everything else — the workbench, the reports, every future question — follows.

**Read [../build-ontology-from-db/references/rules.md](../build-ontology-from-db/references/rules.md)
before touching a declaration.** It is the single source of the fifteen configuration rules and the
failure each one prevents. This skill does not repeat them.
[references/metric-recipes.md](references/metric-recipes.md) has the three shapes that actually need
declarations — a cross-grain ratio whose denominator lives on another object, a grouped metric whose
dimension is two hops away, a two-dimension four-table group-by — each with the TTL, the SQL the
compiler derives, and the value measured on a real ontology. And
[../build-ontology-from-db/references/tuning-log.md](../build-ontology-from-db/references/tuning-log.md)
is the log of failures agents actually made here (reading the engine, answering a count with a class,
vetoing a label) — read it before blaming the ontology for a bad answer. Read
[../build-ontology-from-db/references/pitfalls.md](../build-ontology-from-db/references/pitfalls.md)
when something refuses and
[../build-ontology-from-db/references/gates.md](../build-ontology-from-db/references/gates.md) for the
gate matrix, including the publish gate at the end.

## Ask the compiler, do not read it

`ontology_inspect(ontology_key="logistics")` → every metric, and every refusal **by name**.
`ontology_inspect(ontology_key="logistics", metric="tripCount")` → the compiled SQL, the value under
the guardrails, the plan estimate, the guard's notes — or the compiler's refusal sentence.
`…, question="有多少条线路"` → what the NL layer resolves it to, verbatim.
`…, source_dir="work/logistics"` → the same questions against your COPY, so before/after an edit is
two calls.

Measured reason: an editor that went looking for a matching rule in the compiler's `nl.py` read ~1,000
lines and answered with a dump of the file. The facts it needed were three tool calls away.
**Reading budget: ≤200 lines per read, and read the TTL and the profile — not the engine.**

## The user speaks business; you speak declarations

A person asking for a metric knows the business, not the schema: what the number is called, what
question it answers, how it is worked out in words, what one row of the business is, what is in scope,
and what they want to look at it by. They will never type TTL, a column name or a JOIN — and they
should not have to.

[references/user-intake.md](references/user-intake.md) is the intake form the panel puts in front of
them and the contract for translating it: which answer becomes `:grain`, which becomes `:where`, which
becomes `:formula`/`:numerator`, and what a blank means. **A blank is a question, not a default** —
grain, scope and thresholds decide what the number *means*, so ask them in business words
("按每一趟车算，还是按每一家门店算？") instead of picking the convenient one.

Report back in business terms too: what the number is now, the sentence it answers, which objects it
had to touch, the value, the independent route that proved it, and what a person must still decide.
Never answer a user by pasting declarations at them.

## The loop — in this order, always

1. **Open a copy.** `ontology_open(ontology_key="logistics")` copies the installed ontology into
   `work/logistics/`. The repo is not yours to edit; the copy is.
2. **Read before you touch.** The profile (`*_settings.json`) and the file you intend to change.
   Its namespace, `ontology_dir`, `overlay`, `guard` limits and `features` decide what is legal.
3. **Classify the change** — which file owns it (table below). Editing the wrong file is the most
   common way an edit "works" and changes nothing.
4. **Edit only that file**, minimally.
5. **Verify the number**, not the file: compile it, run it under the guardrails, and check it
   against a **second, independently written SQL route**. A metric that runs is not a metric that
   is right.
6. **Publish**: `ontology_publish(ontology_key=…, source_dir="work/<key>", include=…)`. It re-runs
   the whole suite against a staging copy and refuses on a **new** refusal or a failing gate. Read
   the report you get back.
7. **Report** the staged id, the numbers, the gates, and — by name — what is NOT RUN. Applying is a
   human's click (`ontology_editor`); never claim the ontology is live because you staged it.

## Which file owns which change

| the request | the file | the edit |
|---|---|---|
| "this number should be X, not Y" | `ontology/02-meaning.ttl` | the axiom: which rows are in scope (`owl:intersectionOf` / `unionOf` / `:hasValue`). Never a `WHERE` typed into SQL |
| "group it by region / by month" | `ontology/02-meaning.ttl` (+ overlay `:groupBy`) | the dimension must be a declared property; if it is not, declare it in `01-structure.ttl` first |
| "count it per stop, not per trip" | the overlay's `:grain` / `:universe` | the grain is what makes a number countable; changing it changes every consumer |
| "average instead of sum", "a ratio", "as a percentage" | overlay: `:aggregate`, `:numerator`/`:denominator`, `:scale` | a ratio declares its two metrics, never `sum(a)/sum(b)` by hand |
| "only last 30 days" | overlay `:where` on a **declared** windowed class | a window is a definition, not a SQL filter |
| "this column means something else" | `ontology/01-structure.ttl` | `rdfs:label`, `:physicalColumn`, `:businessDescription`; a rename must keep the property unique per class |
| "the words / questions / aliases are wrong" | the profile: `samples`, `aliases`, labels | every sample must answer or refuse **by name** |
| "the tutorial is wrong / thin" | `tutorial.json` | every `items` name must be declared; one metric step must actually run; one refusal step |
| "it refuses too much / it should be allowed" | the profile's `guard` | decide refuse-vs-narrow from the real data range; a declared metric is **never** windowed |
| "it returns nothing / everything" | introspection, not a declaration | check the data range and the join path before editing meaning |

## Before you edit: is the word missing, or the declaration?

An unanswered question has three causes, and only the third needs a new declaration:

1. **the words** — the profile's `aliases` lack a synonym (`车` → `vehicle`, `趟次` → `trip`);
2. **the label** — `rdfs:label` is not the phrase people type (it is a *label*, not a description:
   `站点准时率`, not `准时率` when the metric counts stops);
3. **the declaration** — the metric does not exist, or its `:where`/`:grain`/`:formula` does not.

Check 1 and 2 first. A missing synonym is not a missing metric, and adding a declaration to fix a
wording problem is how two metrics end up claiming the same question.

## What you must refuse to do

Say no, and say why — these are the requests that destroy an ontology's value:

- **"Change the number to X"** with no rule behind it. A number is an output of a definition. Ask
  which rows are in scope, at what grain, with which threshold.
- **Invent a threshold or a grain.** (`atRiskDriver`, "good route", "recent") — ask. This is why
  some metrics in every build are *refused by name*: the refusal is the honest answer until the
  business decides.
- **Hand-write SQL for a metric**, or add a code path that bypasses the compiler. The compiler is
  the only source of SQL.
- **Add a metric without a `:grain`** and then "make it work" — the compiler's refusal is correct.
- **Write a grouped ratio.** `:aggregate "ratio_of_sums"` with `:groupBy` is refused by name
  (*"sum/count/avg/min/max are"*): split it into an ungrouped cross-grain ratio or a grouped
  additive metric, and say which you chose.
- **Widen `features` or any guard limit to get a number through.** Narrow the question instead, or
  report the refusal.
- **Edit the installed ontology directly** (repo paths). Apply is a human decision with a role and a
  confirmation; a direct write skips every gate and leaves nothing in the audit trail.

## Verification you can run yourself

The repository's compiler is the one the workbench uses. Set `PY` to an interpreter with
`psycopg2` + `rdflib` (this app's own interpreter) and
run the single-metric checker from this skill:

```bash
# compile everything, refusing by name (no database needed)
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json

# one metric: compiled SQL + the number under the guardrails
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json --metric tripCount --sql

# and against your own hand-written route (the only proof that counts)
$PY scripts/check_metric.py --profile ... --metric totalRevenue \
    --independent "select sum(revenue) from trips"
```

`--independent` runs a query **you** wrote, by a different algebraic route, and compares. If they
disagree, the definition and the route disagree — find out which one the business means before you
publish. Never paste the value you got from the compiler into `--truth`.

Also check the edit bit where it should:

- the metric you touched still compiles, and **the refusals you did not touch still refuse** with
  the same words (a rename that silently un-refuses something is a bug);
- if the edit narrows rows, the number **moves** — a change that leaves the number identical usually
  means you edited a declaration nothing reads;
- if you changed a metric name, every consumer moved with it: samples, tutorial `items`, aliases,
  and any `:numerator`/`:denominator` that referenced it.

## The publish gate is the last gate

`ontology_publish` compares this edit's refusals against the installed ones:

- **new refusal → the publish is refused.** A metric that stops compiling is a number that silently
  disappears from a report.
- **carried refusal → it goes through.** Things already refused are the existing backlog.
- **NOT RUN gates are printed by name.** "This profile has no truth map" is not "verified".

Read the returned report in this shape, and put it in your answer:

```
compile: 21 of 24 metric(s) compiled, 3 refused by name
  REFUSED atRiskDrivers: :AtRiskDriver has no owl::equivalentClass axiom — nothing to compile
carried refusals (already refused in the installed ontology): atRiskDrivers, …
gates: PASS
gates NOT RUN (named, not passed): [NOT RUN] R2 …
```

## Done means

- the change is in **one** declaration file in `work/<key>/`, readable by a human;
- the metric's number was checked against a **second** route (or the check is reported NOT RUN);
- a staged publish exists and its report shows no new refusal and no failing gate;
- your answer names what is still refused, what is NOT RUN, and that **apply is the human's click**;
- the workbench numbers move only **after** that click — say so instead of claiming success.

## Requirements (provided by the host, not by this skill)

| capability | why |
|---|---|
| **`ontology_open`** | copies `ontologies/<key>/` into `work/<key>/` — the installed truth is outside your workspace, and shell-copying the repo breaks the boundary and leaves no trail |
| **`ontology_publish`** | the only way back: stages, re-runs compile + gates against a copy, refuses on a new refusal, never installs |
| **file read + write** | the copy is what you edit; one file per change |
| **shell execution** | `scripts/check_metric.py` is the local verification loop |
| **a Python with `psycopg2` + `rdflib`** | the checker imports this app's `sqlgen`/`guard`; the repo's own venv is `<the app's own .venv: the interpreter that runs the backend>` |

Without `ontology_open`/`ontology_publish` the edit is NOT RUN: say so and hand the folder over
rather than writing into the installed ontology by hand.
