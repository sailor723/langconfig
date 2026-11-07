---
name: answer-ontology-question
description: Use when a customer (or a colleague) asks a question in their own words and the answer must be a number the business can defend — clarify the intent against what the ontology declares, let the compiler build the SQL, bound it with the guardrails, and polish the prose only after the numbers are verified. Not "write SQL for this question".
tags: [ontology, natural-language, intent, sql, guardrails, answer]
triggers:
  - When a business question arrives and the answer must come from an ontology, not from hand-written SQL
  - When the same question gives two different numbers and the definition must decide
  - When an answer must be refused because the ontology cannot answer it (and the refusal must say why)
  - When a metric/class/action name must be resolved from the words a user actually types
version: 1.0
author: weiping
---

# Answering a business question with an ontology

The retail reference already does this end to end — `retail_graph/nl.py` plus `sqlgen.py`, `capability.py`,
`guard.py`, and the SPARQL lane in `lane_b.py`. This skill is the shape of that pipeline, in the order
that keeps the number honest. Read [references/pipeline.md](references/pipeline.md) for the module
anchors, the intent JSON, the slot types and the guard knobs; read
[../build-ontology-from-db/references/tuning-log.md](../build-ontology-from-db/references/tuning-log.md)
before blaming the ontology for a strange answer — most strange answers are matching failures, and they
are catalogued there.

**The one rule that decides everything else: the model never writes SQL and never computes.** It picks a
NAME from the menu, and it writes PROSE about a number the compiler produced. Everything numeric is
compiled.

## The four stages

### 1. Receive the question — verbatim, in the user's language

Keep the exact words. Do not "clean up" the question first: the words are the evidence for stage 2, and
a question rewritten before matching is a question nobody can audit. Note the language (it decides the
answer's language) and whether it is a read (a number) or a write (an action).

### 2. Clarify the intent — menu-constrained, rules first

Build the menu from the ontology: metrics (name, label, definition, compiled SQL), classes (name, label,
what defines them), actions (name, parameters, the guard they compile to). Then, in this order:

- **rules first** (~0 ms): token overlap on camelCase names, the author's `rdfs:label`, the profile's
  `aliases`, plus aggregate hints taken from the compiled SQL (`count(`, `sum(`, `max(`). Actions need an
  explicit VERB (`promote`/`promote`/`record`) — a noun must never select an action.
- **a number is answered by a metric or refused by name** — never by a class listing. Measure cues:
  数 / 多少 / 几条 / 率 / 占比 / 金额 / 最多 / 最高 / 排名, and count / sum / rate / how many. A *declared*
  count must find its metric (`订单数` → `orderCount`) even when the class name is shorter; a Chinese noun
  keeps its modifier in front, so `高风险线路` (suffix `线路`) is covered and `订单行` (prefix only) is not.
- **a literal label is final**: if the question contains a declaration's `rdfs:label` verbatim, that is
  the strongest evidence there is — nothing may veto it (`每千公里破损箱数是多少` must reach the metric
  that carries exactly that label).
- **dimensions**: "按 X" / "by X" must resolve to a metric that GROUPS BY X, or be refused with the list
  of grouped metrics. Silently dropping the dimension answers a different question.
- **slots** (`:supportsSlot :TimeWindow` / `:CustomerFilter`): the question's period and customer become
  parameters, not SQL. A complex intent (any slot, or an action) is **echoed back as an understanding
  and needs a confirmation before it runs** — that echo is the cheapest wrong-answer check there is.
- **only when the rules are unsure** does the model run, and it may only return
  `{kind, name, params}` from the menu. Off-menu → refuse by name, listing what is on the menu.
- **validate** the chosen name and parameter types against the menu before executing anything.

Two different metrics that both match is not a tie to break silently: say which two, and ask which
definition the user means (different grain = different number).

### 3. Execute — compile, bound, run

Never write SQL. The intent goes to the ontology's own compiler:

- a metric → `compile_metric` (the joins come from `:references`, the grain from `:grain`, the row set
  from `:where`, the dimensions from `:groupBy`, a ratio from `:numerator`/`:denominator`);
- a class → `concept_sql` / the axiom's predicate;
- an action → a **dry-run** (`actions.check_action`) reporting ADMITTED / REFUSED; the write happens only
  after an explicit confirmation, through the audited lane.

Then the guardrails, and they are not optional: page cap, plan budget, statement timeout, big tables with
their time column. **A declared metric is never windowed** — the guard reports the unbounded scan and the
plan budget decides; injecting a "last 90 days" window into a metric silently changes the number its
definition promises (measured: 3,950 where the definition says 4,050).

### 4. Polish — prose after the numbers, and verified

A model may rewrite the answer into readable prose. It is then **checked mechanically**, and discarded
if it fails:

- every computed number and every result key appears **verbatim**;
- for a grouped answer, every key **and** its value survives;
- an action answer repeats the **ADMITTED / REFUSED** verdict;
- the answer is in the **question's language**.

A polish that fails is thrown away and the deterministic template answers instead — the user still gets
the right number, and the trace says who wrote the answer. A refusal and the understanding echo are
polished with the same checks.

## The second lane: SPARQL over the same definitions

The retail reference runs lane B — SPARQL answered by Ontop over an R2RML mapping of the same tables
(`retail_graph/lane_b.py`, `check_mapping.py`). It exists to prove the declarations, not to replace the
compiler:

- ask the **same** question in both lanes and compare (class counts: lane A compiled vs lane B SPARQL);
- a mapping that is wrong is the biggest silent failure here — the gates check it (M4: every served
  defined concept's predicate is encoded in the mapping SQL; M5: live parity between the lanes);
- **not available is not passed**: no endpoint, no mapping, or no Ontop stack ⇒ report
  `NOT RUN (no R2RML mapping for this dataset / the endpoint is down)`. Never answer a SPARQL question
  from the SQL lane and call it lane B.

## Report like this

```
Q: 按线路版本看破损箱数          (interpreted as metric :damagedBoxesByRouteVersion, rules)
A: v1 = 3,490 · v2 = 4,654       (compiled SQL below; guard: page cap only, no window)
   definition: :damagePer1kStops' sibling — sum of stops.damaged_boxes grouped by routes.version,
   joins from :tripOf and :routeOf
   polished by: template (polish rejected: a number changed)   ← says which one answered
REFUSED  atRiskDrivers: :AtRiskDriver has no owl:equivalentClass axiom — nothing to compile
NOT RUN  lane B parity: no R2RML mapping for this dataset
```

- the number **and** the definition it came from;
- the compiled SQL (a reader must be able to see the joins that were used);
- refusals **by name**, as the backlog — they are the negotiation with the business;
- `NOT RUN` items named, never silently green;
- which stage answered (rules / model) and who wrote the prose (llm / template).

## What this skill refuses to do

- **hand-write SQL** for a question, ever — including "just this once, it is faster";
- **invent a metric** to answer: a question with no declaration is a refusal plus a backlog item;
- **window a declared metric** to make it cheap, or **widen a guard** to make a number appear;
- **answer with a class listing** when the question asked for a number;
- **trust the polish**: an unchecked rewrite is how a number changes in a report;
- **call a lane "passed"** because the other lane answered.

## Requirements (provided by the host, not by this skill)

| capability | why |
|---|---|
| the ontology repo's compiler (`sqlgen.py`, `capability.py`, `guard.py`, `nl.py`) | the pipeline *is* those modules; this skill is their order |
| a PostgreSQL connection for the profile | the number comes from the database, not from a description of it |
| a model backend (DeepSeek or local Ollama) — **optional** | rules answer 0 ms; the model is for unsure interpretations and for prose, never for SQL or arithmetic |
| `scripts/ask.py` | runs one question through all five stages and prints the trace (exit 2 = refused) |

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY scripts/ask.py --profile <ontology>/<key>_settings.json "这句话就是用户问的原话"
$PY scripts/ask.py --profile … "按线路版本看破损箱数" --json        # full trace
$PY scripts/ask.py --profile … "订单收入" --no-polish               # deterministic prose only
$PY scripts/ask.py --profile … "上个月的行程数" --confirm            # a slot question, confirmed
```
