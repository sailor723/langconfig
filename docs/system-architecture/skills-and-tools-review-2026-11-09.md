# Skills & tools review — 2026-11-09

Review of what the wider ecosystem actually ships, measured against what this repository already has,
with a short list of what is worth adopting and what is worth installing.

Everything below was checked against the source, not against blog posts:

- `mattpocock/skills` — read `.claude-plugin/plugin.json` (v1.3.2, **27 skills**) and the bodies of
  `grill-me`, `grilling`, `to-tickets`, `research`, `domain-modeling`, `diagnosing-bugs`,
  `writing-for-agents`.
- `anthropics/skills` — read `.claude-plugin/marketplace.json`: `document-skills` (xlsx, docx, pptx,
  pdf, Apache-2.0) and `example-skills` (12: algorithmic-art, brand-guidelines, canvas-design,
  doc-coauthoring, frontend-design, internal-comms, mcp-builder, skill-creator, slack-gif-creator,
  theme-factory, web-artifacts-builder, webapp-testing), plus a `claude-api` set.
- `modelcontextprotocol/servers` — read the reference-server list and the archive note.
- This repository — 74 registered tools (DB `custom_tools`), 42 builtin skills under
  `backend/skills/builtin/`, the MCP seam in `backend/core/mcp/client.py`.

## 1. Two kinds of "skills", and the test that separates them

The Agent Skills format itself is boring and good: a folder with a `SKILL.md` whose frontmatter carries
`name` + `description`, and a body the agent reads **only when the description matches what it is doing**
(progressive disclosure). This repository already speaks that format, with extra frontmatter (`tags`,
`triggers`, `params`, `version`, `author`) that its own loader and UI use.

What differs is the *stance*:

| Stance | What it does | Cost |
|---|---|---|
| **Process-owning frameworks** (BMAD, GSD, Spec-Kit) | own the workflow: they decide the phases, the artifacts and the sequence | the user loses control; a bug in the process is hard to see and harder to fix |
| **Small composable skills** (mattpocock/skills, anthropics/skills) | each one is a paragraph-level discipline the agent invokes for one task | nothing is owned; the human stays the index |

Matt Pocock's README states the first position as the thing he is reacting to ("Approaches like GSD,
BMAD, and Spec-Kit try to help by owning the process… they take away your control and make bugs in the
process hard to resolve"), and sells the second ("small, easy to adapt, and composable… work with any
model").

**Five checks for "honest"**, applied below. A skill passes if it: (1) ends in something verifiable —
a red/green test, a file, a number, a greyed-out question; (2) does not own a pipeline; (3) is small
enough to read in one sitting and has no service dependency; (4) phrases instructions that survive a
model swap; (5) says when **not** to fire, and when to hand the decision to a human.

## 2. The two skills you named

**`grill-me`** is a two-line router (`disable-model-invocation: true` → *"Call the Skill tool with
'grilling'"*) in front of **`grilling`**, which is the real thing:

- it maps the request as a **design tree**, and works it in **rounds**;
- the **frontier** is every decision whose prerequisites are already settled — those get asked *now*,
  numbered, each with a **recommended answer**, worded so "yes" accepts it;
- facts are the agent's job, never the user's: a fact it cannot look up goes to a sub-agent, and only
  the questions *downstream of that fact* wait;
- it ends when the frontier is empty, and **says so before acting** ("Do not act on it until the user
  confirms you have reached a shared understanding").

That is a discipline this repo would benefit from directly: our own experience this month was that the
expensive runs were the ones where nobody had settled the definition first (the v5 build burned turns on
questions a grill round would have asked in ten minutes).

**`to-tickets`** (with `to-spec` upstream of it) turns a plan into **tracer-bullet tickets**: each a
narrow but complete vertical slice, sized to one fresh context window, each declaring the tickets that
**block** it, published to the configured tracker. It contains the one rule most task-breakdowns miss —
the **wide-refactor exception**: when one mechanical change fans across the codebase, do not force a
vertical slice; sequence it **expand → migrate in batches → contract**, and let the batches share an
integration branch. It also quizzes the user on the breakdown before publishing anything.

Both are MIT. Both are ~20-line bodies with one reference file. That is the quality bar.

## 2b. Where "validation" lives — `to-validation` checked against the sources

You remembered a `to-validation` skill. It is **not** in `mattpocock/skills`: that repo's `main` has
39 `SKILL.md` files (I listed the tree, not the plugin manifest — 21 engineering, 3 misc, 6 in-progress,
8 productivity) and there is no `to-spec → to-tickets → to-validation` family. In Matt's flow validation
is **folded into three other skills**, and it is worth knowing which:

| His skill | What validation is there |
|---|---|
| `tdd` | the red → green loop *is* the check: "Red before green", a good test reads like a specification, behaviour through public interfaces, and the anti-patterns list ("implementation-coupled", "horizontal slicing → you verify *imagined* behaviour") |
| `implement-spec` | a **task graph** with a frontier of ready tickets, each in its own worktree, integrated on a branch; validation is "the tracker closes work", not a per-criterion verdict |
| `triage` | *"Verify the claim"* — for a bug, reproduce from the reporter's steps; for a PR, check it out and run the commands. The output is confirmed / failed / needs-info, and "a confirmed verification makes a much stronger agent brief" |

So the family you remember comes from **other** collections, and two of them are worth reading:

| Source | Idea worth taking | What it gets right |
|---|---|---|
| [`giladresisi/ai-dev-env` → `acceptance-criteria-validate`](https://github.com/giladresisi/ai-dev-env/blob/main/skills/acceptance-criteria-validate/SKILL.md) | locate criteria in a fixed order (plan → `acceptance_criteria.md` → the request → **ask**), then a verdict per criterion: **PASS / FAIL / PARTIAL / UNVERIFIABLE**, each with evidence; a report table with counts | it refuses to start without criteria, and it names the trap that costs most: a **new HTTP URL that 404s is a FAIL, not "unverifiable"**; and deferring an executable surface needs a *structural probe* (import it, run it to its first external dependency, check the wiring) — "covered at unit level" never excuses a CLI nobody ran |
| [`pixeloven/crew` → `plan-validation`](https://github.com/pixeloven/crew) | a **validation gate** is a boolean, stated explicitly ("exit code 0", "PR state is OPEN"), and *"a criterion that can't be verified is a criterion that doesn't exist"* | it turns "looks good" into an exit code, and it treats an uncheckable criterion as an open question rather than a soft pass |

What both lack is any knowledge of *this* repository's evidence — which is where ours differs. Adopted
as `backend/skills/builtin/to-validation/SKILL.md` (v1.0), with:

- the same verdict vocabulary and the same refusal to start without criteria;
- **our** evidence table instead of theirs: `scripts/ontology_gates.py`, `./scripts/housekeeping_verify.sh`,
  `pytest tests/…`, `curl` against the running app, `pg_query`, `tsc`/`npm run build`, `git log` lines;
- the **baseline discipline** this repo actually needs (`pytest` has 20 pre-existing failures, so
  "not worse than the list captured before the change" is a verdict and "the suite fails" is not);
- two hard rules from experience: a green suite is evidence only for the criterion the test *names*, and
  the implementer's own summary is never evidence;
- a stop rule: any FAIL means not done, and the report ends in ship / do not ship / ship with N
  follow-ups.

Companion: `grilling` (§2) settles the criteria; `to-validation` proves them. Both were added in the
same pass and both parse through the real loader (`core/skills/loader.py::load_skill`) and are live in
`/api/skills`.

## 3. What this repository already covers (so we do not copy twice)

42 builtin skills, and the substantial ones are substantial — `build-ontology-from-db` 725 lines,
`sql-analyst` 334, `langconfig-builder` 320, `langgraph-workflows` 316, `git-workflow` 291,
`debugging` 289, `security-review` 286 (line counts of `SKILL.md`).

| Matt's / Anthropic's skill | Local equivalent | Verdict |
|---|---|---|
| `mcp-builder`, `webapp-testing`, `frontend-design`, `data-analysis` | same names already in `skills/builtin/` (205–242 lines) | **already have** — diff, do not duplicate |
| `code-review`, `debugging`, `git-workflow`, `security-review` | present | already have (ours are longer; Matt's are sharper about *when* to stop) |
| `research` | `research-planner` / `research-execution` / `research-pipeline-builder` | ours is a pipeline; his is one paragraph + "cite primary sources, write a file" |
| `to-tickets` / `to-spec` | `ticket-classifier` (classification, not breakdown) | **gap** |
| `grill-me` / `grilling` | nothing | **gap — the biggest one** |
| `domain-modeling` (GLOSSARY.md + `docs/adr/`) | nothing; we have prose docs, no glossary/ADR habit | **gap** |
| `diagnosing-bugs` (build a *feedback loop* first) | `debugging` (ours is a checklist) | **gap in method, not name** |
| `writing-for-agents` (how to write skills/AGENTS.md) | `skill-generator` (how to scaffold) | complementary |
| `handoff`, `retro`, `teach`, `to-questionnaire`, `wayfinder`, `prototype`, `improve-codebase-architecture` | nothing | optional, cheap |

## 4. What to adopt, in three batches

**Batch A — copy and adapt (about a day, highest value per line):**

1. **`grilling`** (+ the `grill-me` router). Changes for us: state the ADR/GLOSSARY paths it must read,
   name the round format, and forbid it from starting implementation (our agents can *act*, so the
   "do not act until confirmed" clause needs teeth: the skill ends by writing `work/<key>/grill.md`).
2. **`to-spec` → `to-tickets`**. Our repo has no tracker, so tickets become one file per ticket under
   `docs/tickets/<n>-<slug>.md` with `Blocked by:` lines — the same shape his local mode uses.
3. **`diagnosing-bugs`** — the discipline is *build the feedback loop first*, with a ranked list of nine
   ways to build one. This is a genuine gap next to our `debugging` checklist.
4. **`domain-modeling`** — introduce `GLOSSARY.md` and `docs/adr/NNNN-*.md`. Our ontology work is
   already a glossary with numbers; the ADR habit is what we lack.
5. **`writing-for-agents`** — the only skill about writing skills; it would have caught the `AGENTS.md`
   errors we fixed this week (dead endpoints, stale counts).

**Batch B — write ourselves (things no external skill knows about us):**

- `metric-question` — grill a KPI before measuring it (fills exactly the hole that produced the v5
  questions).
- `analysis-report` — ask → measure twice → chart → **name the number's source** → state what it cannot
  answer. Ties `sql_analyst` to the ontology gates.
- `data-quality-audit` — null/dup/outlier/timezone pass, with a required list of what was *not* checked.

**Batch C — install (capability, not instructions).** Today's stack for analysis is `pandas 3.0.3`,
`matplotlib`, `openpyxl`, `pypdf`, PyMuPDF. Missing pieces that pay for themselves:

| Install | Why | Where it plugs in |
|---|---|---|
| **DuckDB** (+ `duckdb` Python) | SQL over CSV/Parquet/DataFrame in-process; replaces ad-hoc pandas loops for group-bys and joins; also `read_csv_auto` profiling | `python_execute`, a `duckdb_query` tool, and the data-analysis skill's `chart_type` path |
| **Polars + PyArrow** | columnar, Arrow-native, no pandas copy tax on big files; Arrow is what DuckDB/Frontend exchange anyway | `sqlite_load_csv`, CSV/Excel ingestion |
| **tabulate** or **great-tables** | render a DataFrame as a clean markdown/HTML table — the single most common final step, currently hand-rolled | `save_analysis_result`, report generator |
| **MCP `fetch` + `git` + `time`** (reference servers, stdio `uvx`/`npx`) | our native `web_fetch` is one-shot; `git` tools let an agent inspect history properly; `time` kills a whole class of date bugs | `mcp_manager` config, one dict per server (shape documented in `core/mcp/client.py`) |
| ~~MCP `filesystem`, `memory`, `postgres`, `sqlite`~~ | **skip** — we already have `read_file`/`write_file`, memory tables, `pg_query`/`sqlite_execute`; the reference postgres/sqlite servers are **archived** | — |
| plotly (Python) — conditional | only worth it if we render to **HTML artifacts**; chart.js already covers in-app charts. Adding it without a viewer adds a dependency and no view | decide with Batch D |

## 5. "Better view" — the analysis output is where the reading actually costs time

Grounded in what the app renders today (`chart.js`, `d3-sankey`, `d3-hierarchy`, `pdfjs-dist`,
`react-markdown`; dashboards in `src/features/ontology/dashboardCharts.tsx`; viewers in
`components/layout2/`):

1. **A shared table component.** Today tabular output is markdown tables and ad-hoc renderers. Add one
   `DataTable` (TanStack Table + virtualisation) used by SQL results, workflow results and markdown
   tables: sort, filter, column pin, copy-as-CSV, "show 100 of 12 480". Biggest single win per line.
2. **Charts that answer questions.** The kinds exist (`slope|series|composition|ranked|matrix|parallel|
   treemap|bubble|sankey|hole`); what is missing is interaction: hover values, zoom, copy data, export
   PNG/CSV, and a **one-line caption that says what the chart claims** (the ontology dashboard already
   declares intent — surface it instead of hiding it in the declaration).
3. **One place for artifacts.** A workflow that produces 12 files across 4 steps scatters them through
   the conversation. An "outputs" panel per run (files, charts, tables, decks) with a preview pane beats
   any new chart type.
4. **Numbers that can be traced.** Every metric cell should carry its provenance (`answers:Q7`,
   `table:trips`) — the ontology grammar already requires that at declaration time; the UI should show it
   on demand rather than only in the TTL.
5. **Do not** add a second charting library or a second dashboard generator: we already have one
   deterministic generator plus a React renderer, and having two of each is how the two board species
   (reference vs reporting) started.

## 6. Honest rejects

- **Process frameworks** (BMAD/GSD/Spec-Kit style): the thing this repo least needs is a second pipeline
  owner on top of workflows + agents + skills.
- **Mega-collections** (the "1 000+ skills" lists): a skill is only honest if a human read it. Curated
  sets we can audit: `anthropics/skills`, `mattpocock/skills`. Everything else is a catalogue, not a
  capability.
- **Duplicate MCP servers** for files/memory/PG — the seam exists, but a second copy of a capability is
  a second thing to keep in sync.
- **`plotly` + `chart.js` together**, **`streamlit`-style second app**, **another deck generator**.

## 6b. Defects in the sources we vendored — found while translating, and what was done

Translating 102 skills to Chinese (see §5e of `skill-authoring.md`) put every line of every skill under a
reader's eye, which is the only audit this library has ever had. The defects below were inherited from the
upstream sets or from the generators that imported them. Each is either **fixed in both languages** or
**recorded here as still broken**, so nobody has to rediscover it:

| Defect | Where | State |
|---|---|---|
| `allowed_tools` split into one list item per character, rendering `**Allowed Tools:** [, ", w, e, b, …` into every prompt | `web-search` | fixed; guard: `test_allowed_tools_is_a_list_of_tool_names` |
| `allowed-tools` (Anthropic spelling) ignored by the loader, so 16 skills' tool lists never reached a prompt | 16 skills | fixed in `SkillLoader`; guard: `test_the_loader_sees_a_declared_tool_list` |
| A link target rewritten into a sentence: `(.the \`triage\` skill-labels.md)` | `setup-matt-pocock-skills` | fixed; the importer's slash rule no longer reaches inside a path; guard: `test_no_markdown_link_target_is_reworded` |
| Triggers that were a scrape of the description's first line, or an unfilled `When asked to <overview>` | 24 skills (both languages) | fixed; no placeholder tokens remain |
| Descriptions cut mid-word by the generator (`…technical analysi`, `…Slower but more fl`) | 5 skills | completed in both languages |
| Skills addressed by an id that does not exist (`\`ecosystem-primer\`` instead of `lc-ecosystem-primer`) | 58 skills | fixed; guard: `test_a_referenced_skill_id_is_the_id_that_exists` |
| A second frontmatter block in the body, served to the model as instructions | `web-search` | removed |
| `ask-matt` said "two on-ramps" and listed three | `ask-matt` | count corrected |
| `writing-beats` step 5 said "Loop steps 3–5" from inside step 5 | `writing-beats` | range corrected to 3–4 |
| The `## Examples` section counted as a heading but the examples themselves were untranslated templates | `document-deliverables` | translated as examples |
| **TypeScript approval example does not compile** — undefined `EmailAgentState`, and `state.emailContent` / `state.responseText` do not match the Python node's `email_content` / `draft_response` | `lc-langgraph-human-in-the-loop` | **still broken** — left byte-identical on purpose: it is upstream's code, and inventing a fix inside a translated fence would hide the defect instead of recording it |
| `## This repository's floor` appended to skills where it is irrelevant (it describes *this* repo's backend suite and its 20 pre-existing failures) | the six `lc-*-quickstart` skills | **still there** — the floor is inert advice in a scaffold-a-new-project skill; trimming it per skill is a separate pass |
| The whole library's floor section referenced `ecosystem-primer`, which never existed under that id | 58 skills | fixed (see the row above) |
| `market-wizard`'s id promises market analysis and its body is generic CSV cleaning; `data-analysis`'s `## Edge Cases` is numbered 1–7 beside a `## Mechanics` list numbered 1–5; `ticket-classifier`, `changelog-generator`, `bug-report-analyzer`, `text-summarizer`, `documentation` and `web-search` are stubs — a few lines each, and `web-search`'s body is only its title | 8 skills | **still as found**, disclosed in the Chinese `name`/`description` where it changes what a reader expects (`market-wizard（通用 CSV 清洗向导）`). Renaming an id breaks bookmarks and pins; filling a stub invents content |

The general lesson, which is why this table exists: **a translation is an audit.** Every defect above was
invisible to the loader, the tests, the UI and every earlier review — none of them read the body line by line.

## 7. Where each item lands

| Change | File / path | Effort |
|---|---|---|
| `grilling`, `to-spec`, `to-tickets`, `diagnosing-bugs`, `domain-modeling`, `writing-for-agents` | `backend/skills/builtin/<name>/SKILL.md` (+ `scripts/sync_skills.py` to the DB) | 1 day |
| `GLOSSARY.md`, `docs/adr/` | repo root + `docs/adr/` | 2 h |
| DuckDB / Polars / PyArrow | `backend/pyproject.toml` (+ `uv lock`), `backend/tools/native_impl.py` for a `duckdb_query` tool | 1–2 days |
| `DataTable` | `src/components/common/DataTable.tsx`, used by results/SQL/markdown | 1–2 days |
| Outputs panel | `src/components/layout2/` (one panel per run) | 2–3 days |
| MCP `fetch`/`git`/`time` | `mcp_manager` config (one dict per server), then an agent picks the tools | 2 h per server |

## Sources

- [mattpocock/skills](https://github.com/mattpocock/skills) — plugin manifest v1.3.2, 27 skills ([README](https://github.com/mattpocock/skills))
- [grill-me-skill](https://github.com/RobMitt/grill-me-skill) — a standalone copy of the skill
- [anthropics/skills](https://github.com/anthropics/skills) — official example + document skills (Apache-2.0)
- [Agent Skills standard](https://agentskills.io) and [Anthropic's write-up](https://anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) — reference servers, and which are archived
- [MCP Registry](https://registry.modelcontextprotocol.io/) — the published-server index
- [skills.sh](https://skills.sh/mattpocock/skills) — how these sets are distributed
