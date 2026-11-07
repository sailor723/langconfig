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

**Measurement (2026-11, superseded).** At the time the compiler supported only grouped
sum/count/avg/min/max. It now supports a grouped `ratio_of_sums` **when both sides are declared at the
same grain** — a group's rate is "numerator summed inside the group ÷ denominator summed inside the
group", which is a number only then. A cross-grain ratio is still refused, now naming both grains
(rules.md 17).

**Rule.** Before writing a grouped rate, check the two sides' `:grain`. Same grain → grouped ratio.
Different grains → ungrouped cross-grain ratio (Recipe 1) or a grouped additive metric (Recipe 2).

**Gate.** `D3` (`check_dashboard.py`) weights each grouped rate back to the ungrouped value; a cross-grain
grouped ratio refuses by name, so it shows up in every compile report.

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

---

## T15. The silent 100%: a grouped rate that read only half the declaration

**Symptom.** `:stopOnTimeRateByRouteVersion` compiled cleanly and reported **100%** on-time for both route
versions. The fleet value is 93.6%.

**Measurement.** The two sides carry their predicate differently: `:onTimeStops` uses `:concept
:OnTimeStop` (compiled FROM the axiom), `:overloadedTrips` uses `:where :OverloadedTrip` (a declared
filter). The ungrouped compiler reads `m.concept or m.where`; the first version of the grouped-ratio path
read only `:where`, so the numerator became `count(DISTINCT stops.id)` — numerator and denominator were
the same expression.

**Rule.** A new compile path must read the SAME fields as the path it sits next to, and the gate must be
able to see the difference. Any rate that comes out suspiciously clean (100%, 0%) is a missing predicate
until proven otherwise.

**Gate.** `D3` weighted identities plus `D5`'s independent `overload_v2` SQL both go red when the FILTER
is deleted (proved by mutation, four D3 failures + the D5 mismatch).

## T16. Comparing two grouped queries by row position invents a number

**Symptom.** The first version of the identity check reported a fleet overload rate of **45.5%**; the real
one is 36.8%.

**Measurement.** `overloadRateByRouteVersion` orders by VALUE (v2 80.2%, v1 2.0%) while
`tripCountByRouteVersion` orders by COUNT (v1 2,250, v2 1,800). Zipping the two row lists paired v2's rate
with v1's size.

**Rule.** Any check that combines two result sets must key them (here: on the version string), never zip
by position. Test the check by deliberately reordering one side.

**Gate.** `D3`/`D5` in `check_dashboard.py` key every comparison through `_by_key`.

## T17. `--profile` after the import is a profile that never loaded

**Symptom.** Running `run_dashboard.py --profile …/logistics_settings.json` reported **23 panels
"missing_declaration" — `no metric :tripCount declared`** for every metric in the file.

**Measurement.** `sqlgen` and `guard` read `$APP_SETTINGS` once, at import, to pick the ontology directory
and the overlay (`metrics_ext.ttl`). Parsing `--profile` inside `main()` left the graph without its
overlay, and an overlay-less ontology looks exactly like an ontology whose metrics were never declared.

**Rule.** Anything that selects a profile must set `APP_SETTINGS` before importing the compiler modules
(same failure the samples-reset path hit). A "23 panels missing" report is a load problem until proven
a declaration problem.

**Gate.** `D0` names the panel and the metric; the first honest reading of it is "did the overlay load".

## T18. The write that succeeded and then vanished (a `Decimal` in the audit row)

**Symptom.** The first real `RecordDispatchDecision` run raised a `TypeError` from `json.dumps` *after* the
INSERT, and `dispatch_decisions` stayed empty.

**Measurement.** The audit row is built with `json.dumps` over the returned row; `numeric` columns come
back as `Decimal`, which json refuses. `run_action` caught it, rolled back, and nothing was written — the
transaction discipline worked, the failure was invisible unless you read the traceback.

**Rule.** Every value that goes into an audit/structured column must survive `json.dumps` for real
(`Decimal`, `time`, `timedelta`, `bytes`); the "last resort" is `str(v)`, because an audit row that cannot
be written means the business write cannot be committed either.

**Gate.** `A4` runs a real write and reads the audit row back, so this class of bug fails the gate, not the
user.

## T19. A gate for the data it was written on

**Symptom.** `check_actions.py --profile …/logistics_settings.json` died on
`relation "customers" does not exist` — it is retail's gate, hard-coded to `customers.tier` and `orders`.

**Measurement.** The gate could only pass on retail; on any other ontology it was either broken or "passed"
while checking nothing.

**Rule.** A gate carries the knowledge of the dataset it validates. For a different ontology, either
declare its fixture (`actions_fixture.json` + `samples.json` style) and run a declaration-driven gate
(`check_actions_run.py`), or state `NOT RUN` by name. Never reuse a retail-shaped gate and call it green.

**Gate.** `check_actions_run.py` (A1–A6).

## T20. Adding a verb silently re-routed three measure questions

**Symptom.** After declaring `RecordDispatchDecision`, three sample questions changed their answer:
「派单决策记录覆盖率是多少」 came back as a DRY RUN of the write instead of the coverage number. `N1`
caught it ("got 'RecordDispatchDecision', want 'decisionCoverage'").

**Measurement.** The built-in glossary maps `记录 → "record"`; the question tokenized to `record`;
`_rule_intent`'s verb branch (`VERBS = {promote, demote, record}`) matched before any metric was
scored. So the collision was in the WORDS, and it appeared the moment a verb had a name in the glossary.

**Rule.** A question that carries a measure cue (是多少 / 率 / 覆盖率 / 数 …) cannot be answered by a
verb — an action is reachable only by an imperative. `_measure_cue` already existed for exactly this
distinction; the verb branch now honours it.

**Gate.** `A7` in `check_actions_run.py`: the fixture names one measure question (must resolve to the
declared metric) and one imperative (must still reach the verb). Both run against the real menu.

## T21. A declaration that is only honoured by its own server

**Symptom.** Turning `features.actions` on for logistics made every sample refuse with
*"cannot compile action declarations: :Customer has no :physicalTable"* — retail's verbs compiled
against the logistics graph.

**Measurement.** `actions.SCHEMA` was `APP_ACTIONS or retail's schema/actions.yml`. `serve_ui` sets
`APP_ACTIONS` for the children it spawns, so the workbench was fine; every other reader (the samples
gate, `nl.menu`, an inspection script) silently used retail's file. Making the path profile-aware was not
enough either: `_settings()` reads a PATH bound at import, so a gate that switches `APP_SETTINGS` mid-run
still saw the old profile.

**Rule.** A resolver must read the live environment at CALL time (`actions.actions_path()`), and a profile
field that governs behaviour must be honoured by every reader, not only by the server that happens to set
the env var.

**Gate.** `check_samples` (all samples answering again) · `check_ontology_generic` N/W gates (which run
`nl.menu` from a profile switch).

## T22. One alias poisoned every dimension question

**Symptom.** After declaring the chart channels, the sample 「按门店区域看破损箱数」 started refusing with
*"no declared metric groups by ['coreZonePermit', 'storeZone']"*.

**Measurement.** `_group_dims` matched a dimension when ANY camel word of its property name appeared in
the question's tokens. The profile alias 区域 → `zone` therefore matched `:storeZone` AND
`:coreZonePermit`, producing a two-dimension conjunction no metric satisfies.

**Rule.** Match a dimension by a word that is UNAMBIGUOUS: if two dimensions answer to the same word, the
word decides nothing and is dropped (the label-literal matcher still sees the question). Measured after
the fix: 门店区域 → {storeZone}; 核心区通行证 → {coreZonePermit}.

**Gate.** `check_nl` (retail's grouped questions) + `check_samples` (logistics) both go red on the naive
version.
