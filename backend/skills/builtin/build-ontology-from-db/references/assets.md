# The skill's own assets — what is here, and when you open it

Everything below ships WITH the skill so a builder does not have to invent a shape. Each line says the
ladder step that reads it; a file nothing schedules is a file nobody opens (measured: SKILL.md was read
eight times in one build and no reference was opened once).

## `examples/` — four finished ontologies, as patterns

| path | what it teaches | open at |
|---|---|---|
| `examples/retail/01-structure.ttl` · `02-meaning.ttl` · `metrics_ext.ttl` | the full pattern: one object, one link, an axiom-compiled class, a ratio with both sides written out | **S1 → S3** |
| `examples/clinic-test/01-structure.ttl` · `02-meaning.ttl` · `clinic_settings.json` · `README.md` | a profile with a guard and a sample front door; the README lists what the build itself must decide | **S4 → S5** |
| `examples/abc/01-structure.ttl` · `02-meaning.ttl` · `actions.yml` | declared writes (lane C): a verb with compiled preconditions and an audit trail | **S5 (only if the brief has writes)** |
| `examples/tpch/tpch.ttl` · `02-relationships.ttl` · `metrics_ext.ttl` | a benchmark ontology: many links, benchmark metrics, and a profile that REFUSES windows because the data is historical | **S4 (window refusal), S2 (links)** |

These are copies on purpose: the live versions are under `backend/features/ontology/profiles/`, and those
are the ones the gates run. Read the copy for the pattern, run the original for the proof.

## `scripts/` — three helpers, each one a measurement

| script | what it does | when |
|---|---|---|
| `scripts/introspect_db.py` | phase 1: read a PostgreSQL database and print the decision-shaped brief (tables with identity, links, the time axis, what is constant) | **S0**, before asking anyone anything |
| `scripts/scaffold_ttl.py` | writes the skeleton `01-structure.ttl` from that brief — a starting point to edit, never a finished declaration | **S1** |
| `scripts/check_ontology.py` | the oldest self-check: compile the overlay against a profile and print what refused | **S3**, as a loud second opinion next to `--family C` |

## `params.json` — the wiring the agent carries

`{"skill": "build-ontology-from-db", "datasource": …, "ontology_key": …, "profile_file": …}`. The build
dialog and `builders()` read the ontology key from here, so two builders on one database stay two
ontologies.

## What is NOT here

No thresholds, no grains, no targets, no "acceptable" rates. Those are business decisions; the skill's job
is to make the absence visible (a refusal with a name), not to fill it in.
