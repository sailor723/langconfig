# Tuning log — failures measured on a real agent, and the rule each one became

This file exists because the chat log *is* the evidence. Every entry is a thing an agent actually did
on a real build/edit, with the measurement that caught it and the rule it turned into. Read it when
an agent behaves badly: the failure is probably here already, with the fix that was found.

Format: **symptom → measurement → rule → gate**. If a symptom has no gate, the rule is a hope.

---

## T1. It read the engine instead of asking it

**Symptom.** Asked to add a sample question that must be refused, the editor agent opened
`retail_graph/nl.py` and read ~1,000 lines to work out how matching behaves. Its final answer was a
dump of the file's source, not a report. 22 tool calls, one of them `sed -n 600,706p nl.py`.

**Measurement.** The same turn with a "no more than 8 tool calls, do not read nl.py" instruction
finished in 5 calls with the correct answer. The information it needed was: which metrics refuse and
why, what one metric compiles to, what a question resolves to.

**Rule.** Never read `sqlgen.py` / `nl.py` / `guard.py` to learn a rule. Ask the compiler:
`ontology_inspect(ontology_key=…)` lists metrics and refusals by name;
`metric="tripCount"` gives the compiled SQL, the value under the guardrails, the plan estimate and
the guard's notes (or the compiler's refusal sentence); `question="…"` gives what the NL layer
resolves it to, verbatim. `source_dir="work/<key>"` inspects a copy, so before/after is two calls.
Reading budget: ≤200 lines per read, and the files to read are the TTL and the profile.

**Gate.** The tool's own tests cover the three modes; the skill states the budget.

---

## T2. A number was answered by a class listing

**Symptom.** In the workbench, 「高风险线路数」 was ANSWERED — with a listing of `:Route`. The same
happened for 「哪台车破损最多」 (answered with `:DamagedStop`).

**Measurement.** The question tokenises to CJK 2-grams plus the alias 线路→route; the class `:Route`
won the tiebreak because the tiebreak prefers the *shorter* name (one word vs `overloadsByRouteVersion`'s
four). The salient-noun check that exists for exactly this could not see it: it skips CJK tokens.

**Rule.** A question that asks for a number is answered by a metric or refused by name — never by a
class. Cues: 数 / 多少 / 几条 / 几趟 / 率 / 占比 / 金额 / 最多 / 最少 / 最高 / 最低 / 排名, and the
English count/sum/rate/how many. A **declared** count still finds its metric (`订单数` → `orderCount`)
even though the class name is shorter; a **Chinese noun keeps its modifier in front**, so a suffix
match counts (`高风险线路` ends with `线路`) and a prefix-only one does not (`订单行` is not `订单`).
`行/列/单` are part of nouns, not filler words.

**Gate.** `check_nl.py` N13 (10 assertions: declared count → metric, undeclared count → named
refusal, list request → class) and `check_ontology_generic.py` N2 (superlative is never a class).

---

## T3. It refused a question that quotes a declaration's own label

**Symptom.** On a copy that had `:damagePer1kKm` with `rdfs:label "每千公里破损箱数"`, the question
「每千公里破损箱数是多少」 was REFUSED. The label was an exact substring of the question.

**Measurement.** The label-literal rule picked the metric (score 1000+), then the salient-noun check
vetoed it: the alias 破损→`damaged` had no counterpart in the metric's own words
`{damage, per1k, km}`.

**Rule.** A literal label is final. The author wrote that phrase because people type it; nothing
overrides it (the count/class rule still applies, because that is a fact about the ontology rather
than a scoring detail).

**Gate.** `check_ontology_generic.py` N1: every CJK label + 「是多少」 must reach its own
declaration. 23/23 on logistics, 28/28 on clinic.

---

## T4. The profile loaded an EMPTY graph and nobody could tell

**Symptom.** Every question asked of the logistics workbench was refused with
`I can answer about: metrics [], classes []`. That reads exactly like "this ontology declares nothing".

**Measurement.** `sqlgen._apply_env_profile()` resolved the profile's `ontology_dir` / `overlay`
against **`retail_graph/`** (the engine's folder) instead of the **profile's own folder**. It worked
for retail only because retail's profile happens to sit next to the engine. Every other profile got a
path that does not exist, so the graph loaded empty.

**Rule.** A profile's relative paths are relative to the profile. A loader that cannot find them must
say so, not return an empty graph.

**Gate.** The generic gate run prints the metric count for the profile it loaded; an empty graph makes
every gate fail loudly instead of silently passing.

---

## T5. A metric's number was computed under the wrong guard mode

**Symptom.** `tripCount` came back **3950** from a verification script while the definition says
**4050**.

**Measurement.** The script ran the metric with `guard.run(..., mode="rows")` (the default). That
mode injects `trip_date >= now() - 90 days` on a big table — correct for a *listing*, wrong for a
**declared metric**, whose definition promises the whole set. `mode="declared"` reports the unbounded
scan and lets the plan budget decide.

**Rule.** Any tool, script or gate that runs a metric uses `mode="declared"`. A metric's value is
never windowed.

**Gate.** `guard.metric_not_windowed` per profile; `check_metric.py` asks for `declared` explicitly
and prints the guard's notes so a window would be visible.

---

## T6. A gate rotted because it compared a moving number to a constant

**Symptom.** `check_metrics.py` failed with `got 849.5, want 969.5` for "total revenue last 90 days".

**Measurement.** The metric is correct for its window; the *demo data ages*, so a `now()`-relative
total shrinks. The gate had been failing on a number that was right.

**Rule.** Never compare a `now()`-relative number to a constant. Compare it to an independent route
(the same rows, summed a different way — e.g. per customer then added), which keeps the gate biting
and cannot go stale.

**Gate.** The rule is now the gate's implementation (`check_metrics.py` windowed-revenue case).

---

## T7. "My fix didn't apply" was three backends on one port

**Symptom.** After editing a route, the API still answered with the old OpenAPI and 404s — twice in a
row, after two restarts.

**Measurement.** `lsof -ti tcp:8765` listed three `uvicorn main:app` processes; `kill` of
`$(lsof -ti | head -1)` killed one and the surviving process kept serving (SO_REUSEADDR). Requests
were load-balanced across old and new code, so the same URL behaved differently per call.

**Rule.** Restart by killing **every** listener, then start exactly one and verify the listener count
is 1 before judging behaviour. The same applies to workbench children: they import the engine at
start-up, so an edit to `nl.py`/`sqlgen.py` needs the child killed (by port), not just "ensure
started".

**Gate.** None yet — this is an operator rule; a supervisor could assert one listener per port.

---

## T8. The agent's report was cut off mid-sentence

**Symptom.** A correct, verified answer ended at `1794014588-cbdf3` — the staged id, truncated.

**Measurement.** `max_tokens: 4096`. A verified edit produces a body, two verification blocks and a
gate report; the honest version does not fit.

**Rule.** Budget the token limit for the *report* the skill requires, not for prose: 8192 for an
editing agent. When a refresh rewrites an agent's config, re-bake the identity block — a PUT replaces
`system_prompt` verbatim, and one refresh silently dropped it (measured: 4,347 chars → 1,538).

**Gate.** The agent seed asserts `"## Identity" in prompt` after the refresh.

---

## T9. The contract contradicted the skill, and the agent caught it

**Symptom.** The logistics builder reported, on its own publish: "`logistics_settings.json` has
`features.tutorial: true`, but the workbench contract's fixed values say `false` — if that `false` is
a hard constraint, fix it before applying."

**Measurement.** It was right: phase 9 requires every ontology to ship a tutorial, and both builder
agents' contracts said `tutorial: false`, so the tab would have been hidden.

**Rule.** The contract's fixed profile values are part of the skill's contract; when the skill adds a
required artifact (a tutorial), the fixed values must move with it. An agent reporting a
contract/skill contradiction is doing its job — check it, do not dismiss it.

**Gate.** The builder contract is now `tutorial: true`; the tutorial gates (T1–T4) run per profile.

---

## T10. Asking a typo cost a whole model turn

**Symptom.** A request to publish for ontology `doesnotexist` was accepted; the agent then spent a
full turn producing a plausible report about an ontology that does not exist.

**Measurement.** The chat endpoint validated the message, not the ontology key.

**Rule.** Validate everything the turn will depend on *before* the model runs: key installed, brief
non-empty, message non-empty and bounded. Name the alternatives when a key is wrong.

**Gate.** `tests/test_ontology_editor_chat.py` (four "refused before a turn" cases) and
`tests/test_ontology_build.py` (key with a slash, empty brief).

---

## T11. Generation died with the tab that started it

**Symptom.** A build was one streamed chat turn: closing the tab cancelled the stream and the run
died with it — no queue entry, no progress, no retry.

**Measurement.** The build takes minutes (schema introspection, three TTL files, a profile, a
tutorial, the gate suite several times).

**Rule.** Generation is a **job**. It is a `background_tasks` row with a registered handler, a status,
a step list ("opened session", "agent is reading the database", "gates are green — auto-landing"),
and cancel/retry. Progress is the list of steps that happened — never a percentage: an agent's steps
are not proportional, and a progress bar would be the one thing this project never ships.

**Gate.** `tests/test_ontology_build.py` (12 gates, including "auto-land only on evidence").

---

## T12. A publish report said nothing about what changes

**Symptom.** A reviewer was shown "gates PASS, 20 compiled, 3 carried refusals, 12 files" for a
publish whose actual change was one line of one file — and asked "so what changed?".

**Measurement.** The file count and the gate summary answer "did it pass", never "did my number move".

**Rule.** Every staged publish exposes two views before the apply decision:
**diff** (which declarations change, per file, with +/− counts) and **value delta** (which *numbers*
move: both sides compiled and run under their own guardrails, only the changed ones listed, the rest
counted).

**Gate.** `tests/test_ontology_publish.py` (diff shows only the change; delta reports only the metrics
that move, including a state change compiled → refused).

---

## T13. A grouped ratio is refused, by name

**Symptom.** `:damagePer1kKmByVehicle` (`ratio_of_sums` + `:groupBy :plate`) was refused with
`':aggregate ratio_of_sums' with :groupBy is not supported (sum/count/avg/min/max are)`.

**Measurement.** The compiler supports grouped sum/count/avg/min/max; a ratio grouped by a dimension
is not implemented. Two working alternatives: an **ungrouped** cross-grain ratio, or a **grouped
plain sum**.

**Rule.** Before writing a grouped ratio, ask the compiler (`ontology_inspect(metric=…)`). Then choose:
ungrouped ratio, or grouped additive metric — and say which you chose and why.

**Gate.** The refusal is by name, so it is visible in every compile report.

---

## T14. The question that "obviously" should just work needs an alias, not a metric

**Symptom.** With a vehicle-grouped metric added, 「哪台车破损最多」 still did not reach it: `车` was
not in the profile's `aliases`.

**Measurement.** After adding `"车": "vehicle"` to the profile's aliases, the same question resolved
to `damagedBoxesByVehicle`.

**Rule.** When a question fails to reach a declared metric, first check whether the *words* are
missing (profile `aliases`), then whether the label is the phrase people type (`rdfs:label`), and only
then whether the declaration itself is missing. A missing synonym is not a missing metric.

**Gate.** N1 covers labels; aliases are a profile decision and are checked by the samples gate.
