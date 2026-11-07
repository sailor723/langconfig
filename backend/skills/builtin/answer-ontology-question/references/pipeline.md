# The pipeline, module by module

## Where this lives for ONE ontology

The pipeline is per ontology. What that means in practice:

| surface | what it is | how to reach it |
|---|---|---|
| the ontology's Query section | the page a user asks on | `<workbench>/query` (each profile has its own port) |
| the same thing as an API | one question in, one trace out | `POST <workbench>/api/nl {question, confirm}` |
| the per-ontology menu | what *this* ontology declares | built from `ontologies/<key>/**/*.ttl` at request time |
| the per-ontology samples | the questions a user is offered, and the gate on them | `GET <workbench>/api/samples` (from the profile's `samples`) |
| the per-ontology words | aliases (synonyms) and labels (the phrase people type) | profile `aliases`, TTL `rdfs:label` |
| the per-ontology tutorial | what to read first, and the refusal it teaches | `GET <workbench>/api/tutorial/steps` |

Ask one ontology three ways (same pipeline, three entry points):

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY scripts/ask.py --key logistics "行程数"                 # resolve ontologies/logistics/*_settings.json
$PY scripts/ask.py --workbench http://127.0.0.1:8098 "…"    # the ontology's own Query surface
$PY scripts/ask.py --profile <path/to/*_settings.json> "…"  # an explicit profile
```

The per-ontology gate that keeps this honest is the **samples gate**: every sample question in the
profile must answer, or refuse **by name** — a sample that rots is worse than none, because it is the
first thing a user clicks.

## Module by module

The anchors below are in `retail_graph/`, the reference implementation the other ontologies reuse.
Line numbers are from the current checkout — read the function, not the number.

## 1 · menu — `nl.menu(graph)` (`nl.py:315`)

The ontology's public API, built from the compiled graph (not from a list):

```json
{"metrics": [{"name": "tripCount", "label": "行程数", "unit": "count",
              "formula": null, "grain": "Trip", "group_by": [], "sql": "SELECT …",
              "refused": "…"}],
 "classes": [{"name": "OnTimeStop", "label": "准时站点", "predicate": "on_time = true",
              "sql": "…", "value": 43244}],
 "actions": [{"name": "RecordOrder", "parameters": [...], "dry_run": "…"}]}
```

A metric that cannot compile carries `refused` instead of `sql` — the menu is honest about it, which is
why "this ontology cannot answer X" is a fact the pipeline can state rather than a failure it discovers.

## 2 · interpret — `nl.interpret()` (`nl.py:992`) and `nl._rule_intent()` (`nl.py:661`)

`interpret` tries the rules first (`RULES_FIRST`, `nl.py:414`) and falls back to the model
(`_raw_intent` → `_fallback_intent`) only when the rules return nothing usable.

The matcher's decision order, each one bought with a measured failure:

| rule | what it prevents | where |
|---|---|---|
| label literal wins | a question quoting the author's own phrase being vetoed by a derived alias token | `nl.py` `_by_label` |
| measure cue vs class | a count answered by a listing (`高风险线路数` → `:Route`) | `_measure_cue`, `_count_of_class` |
| declared count lookup | `订单数` refusing although `orderCount` is declared | `_count_of_class` |
| CJK modifier order | `订单行` matching `:Order` | `_zh_covers` |
| dimension claim | "revenue by store" answered ungrouped | `_check_dimensions` (`nl.py:951`) |
| slots | a period or a customer typed into SQL | `_slots` (`nl.py:636`) |
| action verb | a noun selecting a write | `_rule_intent` VERBS |
| salient-noun check | a truncated question answered confidently ("which premium people bought boots?") | `nl.py` uncovered set |

An off-menu or malformed intent is refused **by name** in `validate()` (`nl.py:1015`) — fail closed, no
free SQL, no guessed number.

## 3 · capability — `capability.build()` / `.resolve()`

What a metric is *allowed* to be asked with: slots (`:supportsSlot :TimeWindow`, `:CustomerFilter`) and
filters on declared columns. `resolve()` produces the plan (`capability.edges_text(plan)` is the route a
reader can audit) or raises `CapabilityError`, which the pipeline turns into a refusal.

This is where "the same question, different number" gets decided: a slot that the metric does not declare
is refused rather than pushed down as an arbitrary filter.

## 4 · execute — `sqlgen.compile_metric()`, `sqlgen.concept_sql()`, `actions.check_action()`

- **metric**: joins from `:references` only; grain/universe give the base set; `:where` adds the defined
  class's predicate; `:groupBy` adds the dimension; `:numerator`/`:denominator`/`:scale` compile a ratio;
  `:formula` resolves a column that must belong to the grain class **or to a class reachable through a
  declared relationship** (the refusal lists the reachable set — that list is the ontology telling you
  what it can join to).
- **class**: the axiom's predicate as a `count(*)` over the same base.
- **action**: `check_action` dry-runs the compiled guard and reports ADMITTED / REFUSED. The write itself
  needs an explicit confirmation and lands through the audited lane.

## 5 · guard — `guard.apply()` / `guard.run()` / `guard.plan_rows()` (`guard.py:123`, `:223`, `:171`)

Every read passes through the profile's `guard` block: `max_rows` (page cap), `statement_timeout_ms`
(always `SET`, never `SET LOCAL` — that was a no-op outside a transaction), `max_plan_rows` (the plan
estimate is checked before the query runs), `default_window_days`, and `big_tables` (table → its time
column).

`mode` matters and is easy to get wrong:

- `mode="rows"` (default) — a *listing*: a big table without a time filter gets the window injected.
- `mode="declared"` — a **declared metric**: the window is not injected; the unbounded scan is reported in
  `notes` and the plan budget decides. Use this whenever you run a metric, or you will silently answer a
  different question (measured: 3,950 vs 4,050).

`Refusal` is a result: it names what would have happened and why it did not.

## 6 · answer — `nl.answer()` (`nl.py:1218`)

`answer()` returns `{"text", "source"}`. `source` is one of `llm (<backend>)` or
`template (…)`, and when a polish is rejected the reason is in the parentheses — the trace shows it. The
checks, in code:

- `_language_mismatch()` (`nl.py:1183`) — an English question answered in Chinese is discarded;
- `_answer_trustworthy()` — every number and result key present verbatim, grouped rows intact, action
  verdict repeated;
- a failed polish is not a failed answer: the template answers and the number is still right.

## 7 · telemetry — `nl._record()` (`nl.py:156`), `nl.backlog()` (`nl.py:195`)

Every outcome is appended to `nl_events` (question, ok, refusal_kind, intent, backend). `backlog()`
aggregates the refusals into "what to declare next, from data" — the refusals are the product backlog,
ranked by how often users hit them, not by how interesting they are.

## 8 · the SPARQL lane — `lane_b.py`, `check_mapping.py`

`lane_b.sparql(endpoint, query)` / `count_of(endpoint, iri)` / `served_classes(endpoint)` answer class
questions by SPARQL over Ontop's virtual graph (R2RML mapping of the same tables). It is a **proof lane**:

- `check_mapping.py` M4: every served defined concept encodes its axiom's predicate in the mapping SQL —
  the compensation Ontop cannot do itself;
- M5: live parity — lane A's compiled count equals lane B's SPARQL count for a served class.

Aggregates are the SQL lane's job unless the mapping covers the table. If the endpoint is down or the
mapping is missing, the honest report is `NOT RUN`, never "lane B agrees".

## The gates that keep this honest

| gate | file | what it proves |
|---|---|---|
| menu complete | `check_nl.py` N1 | every declared metric/class/action appears in the menu |
| off-menu refused | N2 | a name that is not declared is refused BY NAME |
| values from the SQL | N3 | the number is the compiled query's, not the model's arithmetic |
| action is a dry-run | N4 | no audit row is written by merely asking |
| fallback + refusal | N5 | with no model the rules still answer or refuse |
| answer carries value and SQL | N6 | the prose cannot drop the number or the query |
| no window on a metric | `check_guard.py` | a declared metric is never windowed |
| intent rules | `check_nl.py` N12–N14 | label-final, count-vs-class, grouped dimensions |
| per-profile labels | `check_ontology_generic.py` N1/N2 | every CJK label reaches its own declaration; a superlative is a number |
| mapping | `check_mapping.py` M4/M5 | the SPARQL lane serves what the ontology says |
