---
name: build-ontology-from-db
description: Use when asked to build an ontology (or semantic layer, or "compile metrics from a database") on top of an existing PostgreSQL database — a step ladder where every step is one artifact plus one gate that can fail, so "done" means green and never means "it looks finished"; it refuses to guess what only the business can decide, and refuses to invent a number the data cannot support
tags: [ontology, semantic-layer, postgres, metrics, data-modeling, sql, gated-build]
triggers:
  - When asked to build or extend an ontology / semantic layer for a database
  - When a KPI or metric must be defined once and compiled, not hand-written per report
  - When "the same metric gives two different numbers" and the definitions must be settled
version: 2.2
author: weiping

params:
  datasource:
    label: 数据库
    description: which database the ontology is built from (the agent's `datasource`)
    required: true
    default_from: agent.datasource
  ontology_key:
    label: 本体
    description: the folder this agent writes (e.g. new_coldchain)
    required: true
  profile_file:
    label: profile 文件名
    description: the profile inside that folder
    required: false
    default: "{ontology_key}_settings.json"
---

# Building an ontology from a database — a ladder of steps, each with a gate

An ontology is not a schema diagram. It is a set of **declarations** from which every number is compiled: change
the declaration and the number moves; change nothing and no report can drift. An ontology that cannot refuse is a
dashboard with extra steps.

**The rule that makes this skill work: a step is finished when its gate is green — not when it looks finished.**
Every step below has an artifact, a command, and a "green" line. A step with no gate is `ungated`, and an ungated
step may never be reported as done.

**Read [references/rules.md](references/rules.md) before writing TTL** (the fifteen configuration rules and the
failure each prevents). [references/pitfalls.md](references/pitfalls.md) is the catalogue of real failures;
[references/tuning-log.md](references/tuning-log.md) is the same for the agent's *own* behaviour;
[references/gates.md](references/gates.md) is the gate matrix and how to prove each gate bites.

## 0. How a step ends (read this before anything else)

For every step, write one entry into `work/<key>/steps.json`:

```json
{"id":"S1","skill_section":"3. structure","status":"green",
 "artifacts":[{"path":"work/<key>/ontology/01-structure.ttl","bytes":21424,"sha256":"ab12…"}],
 "gate":{"cmd":"gates/check_structure.py --profile work/<key>/<key>_settings.json",
         "exit":0,"summary":"88 checks · 0 failed · green"},
 "at":"2026-11-08T00:10:00","by":"agent"}
```

- `status: green` is legal ONLY with `gate.exit == 0` **and** zero failed checks.
- `status: red` carries the failing line verbatim. Never summarise a red gate as "mostly done".
- After any edit, **re-run that step's gate**. An edit without a re-run is unverified.

### Four disciplines that keep a step from stalling (all measured, not stylistic)

The model goes silent when one turn asks it to read a lot AND write a lot. Every rule below is a number from one
afternoon of building one ontology:

- **Append with a shell heredoc — never `edit_file` a file that is already large.** This is the single biggest
  cause of stalls found so far. The same 11 properties took **5.5 minutes with zero output** through `edit_file`
  on a 24 KB file, and **30–40 seconds** through `cat >> file <<'TTL'`. (`edit_file` needs `old_string`/`new_string`,
  so its arguments grow with the file; a heredoc sends only the new text.)

  ```bash
  cat >> ontology/01-structure.ttl <<'TTL'
  :stopOnTime a owl:DatatypeProperty ; rdfs:domain :Stop ; :physicalColumn "on_time" ;
      :businessDescription "该门店是否在收货窗口内到货" .
  TTL
  ```

- **Put the column list IN the prompt.** A turn that must first read a 40 KB `brief.json` (or a 42 KB TTL) to
  learn 20 column names is slow and stalls; the two fastest rounds of the build were the ones where the column
  names were pasted into the instruction (41 s and 97 s for 2–3 classes). If you do not know them, ask the
  database ONE compact question — not a 40 KB introspection dump.
- **One turn = 1–3 classes.** Measured: 6 classes stalled twice (5+ minutes); 2–3 classes completed in 30–120 s.
  Append; never rewrite a finished file.
- **One aggregate, one statement.** Never re-send a query with one more clause appended — that loop produces no
  number for ten turns. If two consecutive tool calls are ≥80 % identical, stop and change the approach.
- **The gate is the only authority; the engine is not.** When a file's format is unclear, open the **gate** that will
  judge it — its docstring holds a complete example. Measured: a turn asked to write `samples.json` instead went
  looking for the schema in `compiler/*.py` and sent **78** `grep` calls, each appending one more filename to the file
  list (`… f1 f2 … fN 2>/dev/null | head -20`), until it hit the recursion limit with the file already written. That
  shape — *the same command with one more argument* — is now what the platform's loop guard looks for (after stripping
  the shared tail, so growth in the MIDDLE of a command counts too), and it trips at the third repeat. If you notice
  you are appending one more item to the same command, stop and read the source of truth instead.

If a turn ends with an empty answer or a link timeout: the artifacts already on disk are the truth. Say which step
is green, which is red, and continue from the red one.

## The ladder

| # | step | artifact | gate | green means |
|---|---|---|---|---|
| S-1 | **重建先证 delta**（仅当本体已装） | `delta.json` | 无自动门；`changed=added=removed=0` 且无 questions ⇒ 输出 `NO DELTA` 并停止 | delta 可解析、逐条对照已装声明、跳过的步骤写明理由 |
| S0 | 读材料 + 澄清 | `draft.json` `questions.json` `answers.json` | 人工确认（无自动门 → `status: human-confirmed`） | 每条声明都能引用 `answers:Qx` 或 `docx#Qn` |
| S1 | 结构层 | `ontology/01-structure.ttl` | `gates/check_structure.py --profile …` | 0 failed：类→表/主键存在、属性→本表列存在、外键带 `:references`、属性名不撞、无孤儿、**每列都被覆盖**、无空类 |
| S2 | 含义层 | `ontology/02-meaning.ttl` | `gates/check_ontology_generic.py --profile … --family R` | 每个定义可编译且选出 >0 行 |
| S3 | 计算层 | `metrics_ext.ttl` | `--family C` | 每个指标编译成功，或**按名拒绝**并进拒绝清单 |
| S4 | 护栏 | profile `guard` | `--family G` | G0–G6 全过（含 G1c：声明的窗口列必须存在） |
| S5 | 菜单/样例 | `samples.json`（格式抄 `check_samples.py` 的 docstring）+ profile `samples` 前门清单 | `gates/check_samples.py --profile …` | 每个样例答出或按名拒绝；`unresolved`/`[WARN] offered but not gated` 逐个点名 |
| S6 | 看板（若声明） | `dashboard.json` | `gates/check_dashboard.py --profile …` | 每个面板引用已声明指标或声明过的洞 |
| S7 | 教程 | `tutorial.json` + 本 profile 自己的 `ontology.html` | `--family T` + 现场 `tutorial/run?metric=…` + `graph_view.py` 末行的自检 | 每个 items 名字已声明；至少一个指标步真跑出数；页面自检 PASS、标题 == profile `title` |
| S8 | 发布 | staged 报告（记 staged id 到 `gates.json` 的 `pending_install`） | `ontology_publish` → `scripts/ontology_gates.py` | stage 编译 0 新拒绝、门全过；整套 suite `0 failed`，未安装的 key 点名 NOT RUN 而不是红 |

**Never skip a step, and never "fix it later".** A red S1 makes every later step meaningless: the compiler will
refuse every metric for the same structural reason, and the time is spent twice.

---

## S-1. A rebuild proves its DELTA before it touches anything

**Read this first when the ontology is already installed.** A rebuild is not "build it again" — it is
"prove what changed, then ask only about the change". Measured on this project: asked to rebuild an
installed ontology from the same documents, one turn spent **285 s and 188 tool calls** exploring the
installed TTL and wrote nothing; the same job with the installed facts **handed over in the prompt**
answered in **12 s with one `write_file`** and the verdict was `changed=0 added=0 removed=0`.

So a rebuild starts with `work/<key>/delta.json`, nothing else:

```json
{"installed": {"objects": 18, "metrics": 28, "samples": 14},
 "items": [{"id": "D1", "kind": "unchanged|changed|added|removed",
            "what": "…", "installed": "…", "document": "…",
            "action": "…", "needs_business": false, "why": "…"}],
 "questions": [{"id": "Q1", "ask": "…", "default": "…", "blocks": "…"}],
 "skip": [{"step": "S1", "why": "structure unchanged"}]}
```

Rules, in order:

- **compare against the installed declarations, not against a blank sheet** — the installed ontology, the
  answers already given (`answers.json`), and the new material are the three inputs;
- **`changed=added=removed=0` and no `questions` → stop and say `NO DELTA`.** Do not recompile, do not
  re-run S1..S8, do not publish. Nothing to build is a result, not a failure — rewriting green
  declarations for a document that agrees with them is how a rebuild turns 12 seconds into ten minutes;
- **conflict → a question, not a decision.** Anything the documents ask for that differs from the
  installed declaration goes into `questions` with a default and what it blocks;
- **`skip` names the steps you are not running and why** ("structure unchanged", "samples unchanged").
  A skipped step with a reason is a decision; a silently skipped step is a lie;
- **`delta.json` must parse.** Write the JSON, and put the summary line in the ANSWER, not appended
  inside the file — measured: a trailing `DELTA done=…` line inside the file made it unparseable, and a
  ledger artifact that cannot be parsed is not an artifact.

Then the ladder runs **only on the delta**: a changed metric is S2+S3, a new column is S1+S3, a new
document section with no declaration consequence is nothing at all.

### The platform composes the seed; do not go looking for it

The rebuild seed (installed objects/metrics/samples, the answers already given, the guard) arrives **in
the first message**. If it is missing, that is a platform bug worth naming — do not spend the turn
reading `01-structure.ttl` (597 lines) to rebuild a list the platform already had.

---

## S0. Read the material, then clarify (two in, three out)

Inputs: a **business document** (the user's own words — targets live there, not in the database) and an existing
**database**; when a mock-data agent ran first, also its `dataset.manifest.json`
(`units / nulls / pii / decisions / refused / handoff`).

Do **not** start writing TTL. Produce, in this order:

1. **`draft.json`** — the picture, every claim carrying evidence:
   `objects[{class, table, grain, rows, evidence}]`,
   `metrics[{name, label, status: supported|needs-decision|refused, definition, evidence, preview}]`,
   `refusals_expected[]`. `evidence` names the column or constraint; `preview` is a real measured number.
2. **`questions.json`** — at most 12, and only questions whose answer **changes a declaration**:
   `{id, ask (business words, no table names), options[], default, blocks, evidence}`. Put the measured number in
   the options: "准点率按站点算 94.6%、按整趟算 53.9%，你要哪个？" is answerable; "准点率怎么定义" is not.
3. **`answers.json`** — `{id, answer, assumed: true|false, becomes}`. A defaulted answer is fine and says
   `assumed: true`. Unanswered is not a blocker; silent invention is.

**A threshold, a grain, a "good route" definition, a target value: none may be invented.** If the document does
not say, the answer is either a defaulted question (recorded as assumed) or a refusal.

### When the data cannot support a target metric: ask the SOURCE, then mock it

The business asks for a metric the schema cannot serve (this happens constantly — "毛利" needs costs the export
never had). Never quietly compute a proxy. The order is:

1. name the missing field and what it would unblock;
2. record the decision (`{"id":"D-cost","text":"向 NASS 追加成本导出","status":"confirmed"}`);
3. **extend the dataset the way that source would** — a new table (`trip_costs`), an added column with a real
   `as_of`, a settlement table — and assert it in the dataset spec;
4. keep what is still missing as **NULL, never 0** (`other_cost` 100 % NULL means 毛利 is an upper bound);
5. re-run the dataset build and confirm the **existing numbers did not move** (adding a table must not shift the
   generator's random stream; derive new columns in SQL, or use an independent stream).

If the business document says something is out of scope (温控 second phase, 贷款压力 not in the system), **do not
mock it** — record it as confirmed-excluded and let the ontology refuse it by name.

---

## S1. `ontology/01-structure.ttl` — objects, keys, columns

One class per table; one property per column; **an FK becomes an object property, not also a data property**.

```ttl
@prefix : <https://example.org/onto#> .
:plate a owl:DatatypeProperty ; rdfs:domain :Vehicle ; :physicalColumn "plate" ;
    :businessDescription "脱敏后的车牌：保留省市与发牌字母，后缀是序号" .
:driverVehicle a owl:ObjectProperty ; rdfs:domain :Driver ; :physicalColumn "vehicle_id" ;
    :references :Vehicle ; :businessDescription "司机带车加盟：一台车一位司机" .
```

Hard rules — each is a failure that has already happened:

- **Property names are unique per class**: `:tripDate`, not `:date`. In RDF one local name is ONE property; `:id`
  on six classes becomes a property with six domains and the compiler then refuses it as ambiguous everywhere.
- **Every column of every modelled table gets a property.** A class that names its table and declares nothing is
  empty scaffolding, and the gate fails it.
- **An FK column is the link only** — declaring it twice makes one relationship two things.
- `:businessDescription` is one sentence of business language; it is what a reviewer reads.

A **composite key is one comma-separated literal** — `:primaryKey "route_id, seq"` is the convention this repo
already uses (clinic's `treatment_lines`, logistics' `route_stops` and `driver_stats`).

Build the file in rounds, and **run the gate after every round**:

```
python backend/features/ontology/gates/check_structure.py --profile work/<key>/<key>_settings.json
```

It diffs the file against `information_schema`: class → table and key exist; data property → column exists **on
its own class's table**; object property → column + a `:references` target whose key exists; no property name
shared by two classes; no orphan property; every table modelled; **every column covered**; no property-less class.
Green = `0 failed`, and `columns_missing` at 0. It runs before anything compiles — that is the point.

**A real build, as a ladder of rounds** (the ledger records each one): 6 classes → `columns_missing` 104; 2 more →
77; 1 (Stop, after switching to heredoc) → 66; 1 → 56; 2 → 46; 1 → 37; 2 → 0. Twenty minutes, every round green
where it should be, and the two red rounds are in the ledger with the reason.

**The gate can be wrong too.** The first run of this gate failed two classes on
`:primaryKey "route_id, seq"`, because it looked for a column literally named `route_id, seq`. Split composite keys
on commas — when a gate and a declaration disagree, find out which one is right *before* editing the TTL, and say
which it was.

---

## S2. `ontology/02-meaning.ttl` — what a word means

For each metric in the draft, ask "what does this MEAN in the business's words", then declare it:

```ttl
:LateStop owl:equivalentClass [ owl:intersectionOf ( :Stop
    [ a owl:Restriction ; owl:onProperty :onTime ; owl:hasValue false ] ) ] .
```

`owl:intersectionOf` = AND, `owl:unionOf` = OR, `owl:hasValue` = a code, `:physicalPredicate` = the ONE escape
hatch (`IS NULL`, column-vs-column) and it must say so in a comment. A class with both an axiom and a declared
predicate is refused.

Gate `--family R`: every definition compiles **and selects rows** — a definition that selects nothing defines
nothing.

### The one thing the compiler will not do: cross a table

Measured over five rounds of this build, four shapes recur every time. They are contract, not taste:

| what the business asks for | what does NOT compile | what does |
|---|---|---|
| a predicate over two columns (`boxes > capacity`) or `IS NULL` | a restriction containing two properties | `:physicalPredicate "load_weight > weight_capacity_snapshot"` on the class, and **column names unqualified** (`amount IS NULL`, never `c.amount IS NULL` — the compiler writes the `FROM` itself, and an alias makes it `missing FROM-clause entry`) |
| a definition that only has `:physicalPredicate` | anything that finds its table by itself | the class also gets `:physicalTable`, and **C1b needs a metric that declares `:where` on it** — order: definitions → counting metrics → gates |
| a definition over another table (`this trip's stops were all on time`) | `EXISTS`/subquery in a predicate | denormalise the state onto the fact row (`trips.late_stop_count`, `stops.handler_days_worked`) and declare a single-table facet |
| a 1:1 detail table (`trip_costs`) feeding a trip-level total | `JOIN` inside a formula | collapse the total onto the fact row (`trips.cost_total`), keep the detail for drilling |
| a **dimension** that lives on another table (`route.version` to compare before/after the merge) | any `:groupBy` reaching across tables | denormalise the dimension onto the fact row (`trips.route_version`) and declare `:groupBy :tripRouteVersion` |

The last row is this round's addition: 并线前后超载 was a headline question, and it was unanswerable not because the
data was missing but because the version lived one table away. Denormalising it took eight lines of SQL derived
columns in the generator and no change to any existing number (verified: ontime 0.94596, external 0.10121, margin
0.51506 all identical before and after).

A definition class that carries **both** `:physicalPredicate` and `:physicalTable` is a definition, not a structure
class: the table is there for C1b to know what to count, and the overview page now classifies definitions first
(measured: it used to report "18/21 classes list their properties" and red-flag a correct ontology).

---

## S3. `metrics_ext.ttl` — the computation overlay

Meaning and computation are separate files on purpose. This one holds `:aggregate`, `:grain`, `:universe`,
`:where`, `:groupBy`, `:numerator`/`:denominator`/`:scale`, `:unit`, `:askedAs`.

- a ratio declares numerator/denominator (never `sum(a)/sum(b)` typed by hand);
- the threshold lives **once**;
- a metric with a `:formula` but no `:grain` **must refuse** — that refusal measures what a semantic layer was
  holding implicitly;
- **every metric's `:businessDescription` names its source**: `口径来自 answers:Q2` or `docx#Q10`. A metric with no
  source is not declared — it goes on the refusal list with the missing question named.

Gate `--family C`: every metric compiles, or refuses **by name** with a sentence a reviewer can act on. The
refusal list is a deliverable and is printed at the end.

---

## S4. Guardrails — decide refuse-vs-narrow for THIS data

Read the manifest's `time` block before choosing anything:

- data is **recent** → a `now()`-relative window is meaningful (`default_window_days: 30/90`);
- data sits in a **fixed historical window** → **refuse** instead of narrowing (`default_window_days: 0`), because
  a relative window silently returns nothing;
- always: page cap (`max_rows`), plan budget (`max_plan_rows`), statement timeout;
- **`big_tables` only for tables that have their own time column** (`trips.trip_date`, `telemetry.ts`,
  `complaints.opened_at`);
- a big table **without** its own time column (`stops`: its date is `trips.trip_date`, one join away) goes in
  `large_tables` — budget only, no injected window. Declared in `big_tables`, the guard injects a window on a
  column that does not exist and **every read of that table dies**.

Gate `--family G`: page cap, window-or-refuse, plan budget (incl. fan-out), statement timeout, a declared metric
is never windowed, an empty window is reported, and **G1c** — every `big_tables` window column exists.

---

## S5. Menu, names, samples

- every metric gets a `rdfs:label` in the user's language and an `:askedAs` a question can match;
- per-profile aliases for words that mean different things per dataset;
- `samples.json`: 8–15 questions, one per capability, **at least one that must be refused**, each stating what it
  must produce (`value`, `rows`, `refused_by_name`) with numbers from a **second SQL route**;
- what the ontology cannot honour yet is `unresolved`, **with the missing declaration named**;
- the questions the profile offers (`settings.samples`) are the front door: a question offered but not gated is
  named `[WARN] offered but not gated`, because a sample nobody checks is the one that rots.

Gate `gates/check_samples.py --profile …`: every sample answers, or refuses by name. A rotten sample is worse than
no sample.

### Read the gate before you write its input

`samples.json`'s shape is in the gate's own **docstring** — `{"samples": [{"question": …, "expect": {...}}]}`,
with `value`/`rows`/`refused_by_name`/`unresolved` and a `tolerance`. Writing it from memory is how a turn spends
**204 tool calls** hunting for a format that was 15 lines above the code it was grepping:

- a bare JSON list → `AttributeError: 'list' object has no attribute 'get'`;
- the key `q` instead of `question` → every sample silently becomes `''` and the gate asks about nothing.

So: **open the gate, copy its example, fill in the numbers.** One read beats seventy greps, and the gate's docstring
is the only spec that cannot drift from the gate.

### The gate verifies; you don't verify 13 questions by hand

The numbers come from a **second SQL route written by whoever has the data in front of them** — not from the
pipeline's own output, and not from the agent re-running thirteen queries to reassure itself. Measured: told to
"run each sample's second route first", the builder spent 204 tool calls and died on `Recursion limit of 400` with
no `samples.json` on disk. The shape that works is two moves:

1. hand over the finished content (numbers already measured) and say **write this file, then run this one gate**;
2. if the gate goes red, the *expectation* is what gets fixed — never the tolerance. Widening a tolerance to reach
   green is how a sample stops being a gate.

### The second route must use the SAME口径 as the declaration

`:OverloadedTrip` is declared as **weight only** (`load_weight > weight_capacity_snapshot`). A second route written
as "boxes OR weight OR volume" measures a different word and disagrees on purpose: v1 5.5% / v2 80.1% versus the
declared 2.65% / 75.4%. Both numbers are right; only one is the declared metric. **One measurement word per
ontology** — either change the predicate and re-declare, or measure the declared one. A gate that disagrees because
the second route drifted is red on you, not on the ontology.

### Grouped samples: the key is a value, the value is a number

`{"rows": {"v1": 0.02654, "v2": 0.75395}}` — the keys are the rendered group values (`True`/`False`, `v1`/`v2`), so
they must be written exactly as the compiler renders them. And a grouped metric has **no single value**: any code
that reads `value` on it is reading the group key. `tutorial_api.run_metric` now answers
`grouped: true, rows: [[key, value], …], row_count: n` and leaves `value` null — measured because it used to report
`value: "v2"` for a grouped overload rate, which a reader can take as the answer.

### Three shapes of a wrong answer

`unresolved` is not only "it refuses". This build shipped three answered-wrong cases, each naming what is missing:

- **a subset answering for the whole** — "所有赔付成本（含未判定）" answers 543,309.02, because `:universe` is
  `:JudgedComplaint`; the 46.1% unjudged is a state, not a zero;
- **a dropped qualifier** — "司机的贷款压力分布" answers a Driver headcount (60): the class matched, `贷款压力` was
  never proven, and nothing refused;
- **a measure turned into a dimension** — "按线路版本看超载" (率 dropped) answers a Route listing (90).

Log all three with the missing declaration named. A red sample would be kinder, but `unresolved` is the honest
label until the declaration exists.

---

## S6. Dashboard (only if the business asked for a board)

`dashboard.json` names which **declared** metric each panel shows, by what it is cut, and what a missing one
costs. A panel that cannot answer ships as a refusal card.

Gate `gates/check_dashboard.py --profile …`: every referenced metric is declared or a declared hole; each metric
has the shape its panel needs; independent SQL agrees; a grouped rate weights back to the ungrouped value.

---

## S7. Tutorial — an ontology nobody can read is a database with extra steps

`tutorial.json` next to the profile: 6–10 steps ordered by the reader's question, in the user's language. Every
`items` name must be **declared**. At least one metric step must actually run (`…/tutorial/run?metric=…`), and at
least one step must be a **refusal** — the most valuable thing you ship.

Gate `--family T` plus a live `GET /api/ontology/{key}/tutorial/run?metric=…` returning a value and `plan_rows`.

Two shape traps, both measured:

- **a grouped metric returns rows, not a value** — `run_metric` used to answer `value: "v2"` for a grouped overload
  rate. It now returns `grouped` + `rows` + `row_count`; the workbench page prints `v2 → 0.754 · v1 → 0.027`
  instead of a dash.
- **the refusal step's items must still be declared names.** This ontology compiles all 28 metrics, so there is no
  declared-but-refused metric to feature. The step therefore names two declared objects (`Telemetry`, `Driver`) and
  teaches the refusals that exist: "温度趋势" (no trend metric, telemetry covers 2.8 h) and "还款压力" (no column,
  and the fuzzy matcher answers a headcount — say that out loud).

---

## S8. Publish through the channel — the ontology lands itself

```
ontology_publish(ontology_key="<key>", source_dir="work/<key>", note="…")
```

It copies over a **staging copy of the installed ontology** and re-runs compile + gates there: every metric
compiled or refused by name, every gate. A publish that introduces a **new refusal** or a **failing gate** is
refused at stage time; carried refusals are listed separately. It **never installs** — a human with the
`ontology_editor` role confirms `apply`, which re-runs the gates on the installed path and commits.

Then record the step and run the suite for this key:

```
python backend/scripts/ontology_gates.py --key <key>
```

Green = every declared family passes and every `NOT RUN` is named. A new key also needs its declaration in
`gates.json` — without it the suite fails with "has no gate declaration", which is the design working.

### The staging copy gates YOUR page too, so generate it first

Stage runs the whole build track against the staging copy, and two checks bite a first-time profile:

- `P2 the profile has its own generated page` — `ontology.html` must exist **next to the profile**. Generate it with
  the same arguments the workbench uses (the profile's own `ns`/`ontology_dir`/`overlay`/`dsn`/`title`):
  `graph_view.py --ns <profile ns> --ontology-dir <profile>/ontology --overlay <profile>/metrics_ext.ttl --dsn … --title "<profile title>" --out <profile>/ontology.html`.
  Its own last line is a gate — `56/56 positioned, 56/56 documented, 18/18 classes list their properties — PASS`. A
  red line there is a real defect in the TTL, not a formatting nit.
- `P2 the page's title is this profile's title` — the page title must equal `settings.title`. A profile whose
  `title` is its own key (`"new_coldchain"`) gets a page titled `new_coldchain`; give it the business title.

### Staged is not installed

Staging writes `<profile>/.staging/<id>/` and nothing else, so the key has **no profile file** and its own gates
cannot run yet. That is a named `NOT RUN`, not a pass and not a failure: record the staged id in `gates.json`
(`"pending_install": "staged <id>: compile 28/28, gates PASS, 1 NOT RUN (R2)"`) so the suite prints the reason
instead of failing on a missing profile. Measured false red: before that, `check_chapters` enumerated the staging
directory as a profile, asked for five pages, got five 404s and turned the suite red about an ontology nobody had
installed — an enumerator must require a profile file, and a staged-only key is pending, not broken.

---

## The refusal list is the deliverable

```
REFUSED  temperatureTrend : 遥测只覆盖 2.8 小时/1,030 趟 → 画不出趋势（docx Q3/Q19 范围外）
REFUSED  loanPressureRanking : 无该列，docx Q14 明确不纳入系统；不造代理列
REFUSED  fullCompensationCost : 46.1% 未判定是状态，不是 0；只能报已判定部分
```

Ship it with the numbers. It is the backlog and the negotiation with the business.

**A gate that cannot fail is decoration.** For every family know the mutation that turns it red (change one
expectation, drop one `:references`, remove one `:grain`, point a property at a column that does not exist) and
say that you ran it. If you have not seen a gate fail, you do not know it works.

## What this skill will not do

- invent a threshold, a grain, a dimension, a target, or an "acceptable" rate — ask, or refuse
- write a number into SQL, a report, or a test
- accept SQL from a caller (the compiler is the only source of SQL)
- claim a metric is right because it ran — ground truth is a second, independent query
- ship a profile without its gates, or a gate that cannot go red
- treat a refusal as a failure: refusals are the contract
- mock a data source the business explicitly excluded — out of scope stays out of scope

## Requirements (provided by the agent/host, not by this skill)

| capability | why |
|---|---|
| **shell execution** (`execute` / `bash`) | the step scripts and every gate run against the real database |
| **file read + write** | the TTL, profile, samples, tutorial and `steps.json` are files |
| **a PostgreSQL connection** | introspection and every gate use the real data, never a description of it |
| **a Python with `psycopg2` + `rdflib`** | scripts and gates import them; the host app's venv has both |
| **the `ontology_publish` tool** | the build lands through the validated channel; without it say publish is NOT RUN |

## Not this skill's job

| hands off to | why |
|---|---|
| the host app's UI (profiles, tabs, pages) | the skill stops at ontology + profile + gates |
| writing to the database (actions, audit) | a declared-action concern with its own review; here only `:state "action"` marks what a write may own |
| deciding a threshold, a grain, a business rule | the S0 clarification loop; guessing them is the failure this skill exists to prevent |
| R2RML / OBDA mappings for a SPARQL lane | a different mapping discipline, and it needs its own gate |

## Working with the human

Ask in this order: (1) the draft, (2) the definitions, (3) the refusals — each with real numbers from the real
database, and say plainly which numbers are unverified. When you find a bug in the compiler or a gate while
building, fix it and say so: the bug is evidence, not embarrassment.
