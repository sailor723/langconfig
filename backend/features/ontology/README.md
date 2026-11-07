# The ontology feature

An ontology is a layer that describes a company's data **in its own words** — objects, the links
between them, and what each number means — so every report, dashboard and agent computes from the same
definitions instead of re-deriving them in SQL.

This directory is that layer, as a feature of the application:

```
compiler/    the compiler. `sqlgen.py` turns declarations into SQL; `guard.py` bounds every read;
             `actions.py` + `capability.py` are the write verbs and the question pipeline; `nl.py` maps
             a question in the user's words onto a declared metric; `graph_view.py` draws the graph page.
workbench/   the static pages (graph, query, actions, design, retail's eight tutorial chapters, ABC's
             training steps) and `serve_ui.py`, the DEVELOPMENT server that could serve one profile on
             its own. The app serves those same pages itself and does not need this process.
gates/       the checks that hold the declarations honest. Thirteen of them; every one can fail.
profiles/    the DECLARATIONS, one directory per ontology:
               ontology/01-structure.ttl   objects, their tables, their links
               ontology/02-meaning.ttl    what a word MEANS (axioms)
               metrics_ext.ttl            the computation layer (a metric = grain + universe + one filter)
               dashboard.json             which declared metric each panel shows
               samples.json               the questions a user can click, with the numbers they must give
               tutorial.json              the tutorial steps
               schema/actions.yml         the declared write verbs
               <key>_settings.json        the workbench profile (DSN, guardrails, features)
```

## The invariants this feature keeps

1. **One definition per number.** A metric is declared once and compiled; a report never re-derives it.
2. **A refusal is a result.** What cannot be answered says WHICH declaration is missing — by name.
   A panel that cannot answer renders as a refusal, not as an empty box.
3. **The gates can fail.** A check that cannot fail is decoration: each one has a mutation that turns
   it red, and the mutation is written down next to it.
4. **No path depends on where the repository lives.** Everything is addressed relative to this file
   (`_paths.py`), because a path to somebody else's machine is a bug that only shows up elsewhere.
5. **The declarations are the deliverable; the code is the tool.** The ontology repository keeps a
   learning mirror of this material, but nothing at runtime depends on it.

## Running it

```bash
# the checks (from this directory)
PY=/path/to/the/interpreter/with/rdflib-and-psycopg2
$PY gates/check_dashboard.py    --profile profiles/logistics/logistics_settings.json   # 196 checks
$PY gates/check_actions_run.py  --profile profiles/logistics/logistics_settings.json   # 22 checks
$PY gates/check_ontology_generic.py --profile profiles/logistics/logistics_settings.json
$PY gates/check_samples.py      --profile profiles/logistics/logistics_settings.json

# the workbench on its own (debugging, teaching)
$PY workbench/serve_ui.py --settings profiles/logistics/logistics_settings.json --port 8098

# the dashboard's own numbers
$PY compiler/run_dashboard.py --profile profiles/logistics/logistics_settings.json
```

## What the application uses it for

Everything below runs **in the app's own process**: the compiler binds its profile per request inside
`services/ontology_runtime._LOCK`, so two ontologies never share a binding (M2).

| app surface | endpoint | module |
|---|---|---|
| the dashboard page | `GET /api/ontology/{key}/panels` · `/ask` | `services/ontology_dashboard.py` |
| the schema & metrics page | `GET /api/ontology/{key}/document` · `/metrics/cards` | `compiler/ontology_api.py` · `compiler/tutorial_api.py` |
| the question panel | `POST /api/ontology/{key}/ask` · `/wb/nl` | `compiler/nl.py` |
| the declared writes | `GET/POST /api/ontology/{key}/actions[/{name}]` | `compiler/actions.py` |
| the graph / design / tutorial pages | `GET /api/ontology/{key}/page/{name}` | `services/ontology_pages.py` |
| retail's eight chapters · ABC's training steps | `/tutorial/chapter/{n}` · `/abct[/{n}]` · the `/wb/…` JSON behind them | `services/ontology_tutorial_chapters.py` |
| which sections an ontology offers | `GET /api/ontology/{key}/sections` | the profile's `features` |

`services/ontology_workbench.py` is the only remaining shell-out, and it is a **development tool**: it can
start one `serve_ui.py` per profile so a page can be edited in isolation. No UI path calls it, and
`GET /api/ontology/workbenches` reports state without starting anything unless `ensure=true`.

## The check that the workbench is really gone

`scripts/check_chapters.py` (declared in `gates.json` for retail and ABC, run by
`scripts/ontology_gates.py`) fetches every section page and every chapter from the **running app**,
reads the endpoints out of each page's own JavaScript, and calls all of them — 209 checks: no bare
`/api/` path survives the rewrite, every referenced endpoint answers (an empty POST must get a verdict,
not a 500), chapter 4's dry run reports `admitted` and binds its parameters, a refused run leaves no audit
row, and a profile without chapters refuses by name instead of borrowing retail's.
