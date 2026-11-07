# The ontology feature

An ontology is a layer that describes a company's data **in its own words** — objects, the links
between them, and what each number means — so every report, dashboard and agent computes from the same
definitions instead of re-deriving them in SQL.

This directory is that layer, as a feature of the application:

```
compiler/    the compiler. `sqlgen.py` turns declarations into SQL; `guard.py` bounds every read;
             `actions.py` + `capability.py` are the write verbs and the question pipeline; `nl.py` maps
             a question in the user's words onto a declared metric; `graph_view.py` draws the graph page.
workbench/   the standalone server that serves ONE profile on its own (`serve_ui.py`) plus the static
             pages it serves. Useful for debugging and for teaching; the app does not need it.
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

| app surface | calls |
|---|---|
| the dashboard page | `compiler/run_dashboard.py` (via `services/ontology_dashboard.py`) |
| the question panel | the `answer-ontology-question` skill's `ask.py` → `compiler/nl.py` |
| the declared writes | `compiler/actions.py` (via `services/ontology_actions.py`) |
| the schema & metrics page | `compiler/sqlgen.py` in-process |

The two `services/` modules shell out on purpose: the compiler binds its profile and its
`APP_ACTIONS` file **once per process**, so a per-request child process is the honest way to serve
two ontologies from one backend (the samples-reset lesson).
