# Ontology agents: one builder, many ontologies, numbered versions

Status: **live** (2026-11-12). Versioning, the single builder template and the retirement of the six
per-key builder rows are done; what remains is listed at the end.

## The decision

A customer says a **name**, not a version: 「新鸿」 → `sunhing`. The platform assigns the version, so
a new ontology is **never written over an older one**:

| What a human says | What the platform builds |
|---|---|
| `--base sunhing` (first time) | `sunhing_v1` |
| `--base sunhing` (again, months later) | `sunhing_v2`; `sunhing_v1.superseded_by = sunhing_v2` |
| `--key abc` (a legacy name with no version) | `abc`, recorded as its family's v1 |

Why never in place: the key is quoted by a published URL, a Settings row, a staging directory, a
publish history entry, a gate declaration and a `.env` variable. Overwriting it moves all six
silently; a new number moves none of them.

Why one builder template instead of one agent per key (measured on the nine ontology agents that
exist today): the seven builder prompts were the same text with four substitutions — `sunhing_v1`,
`chinook`, `meeting_hub`, `clinic_db` — copied into 348/349/355/376/378/379. The tools underneath
(`ontology_open`, `ontology_inspect`, `ontology_publish`) already take `ontology_key` as an
argument, and 348/349 carry a 9-tool set while the rest carry 11, so the copies had already
diverged. One template plus a per-key instance is the same product with one prompt to fix.

## Rules the code enforces

`backend/features/ontology/versioning.py` is the only module that assigns numbers.

1. Next number = **max over everything that exists** (registry, `profiles/` directory, `gates.json`
   declaration) **+ 1**. A key registered by any route still gets a free number.
2. A number is **never reused** — not after a delete, not after a failed build, not when the next
   build is smaller. Removing `sunhing_v3` from disk does not make the next build v3.
3. Exactly one build per family is `latest`. Every older build keeps `superseded_by` pointing at
   the build that replaced **it**, so the chain walks both ways (`v1→v2→v3`).
4. `kind` is required and recorded:
   - `customer` — a client deliverable; nothing in the repo deletes it.
   - `demo` — a shipped illustration that must keep running (TPC-H, retail, logistics, clinic, the
     talent ontology behind the hiring feature, the measured ebl/eff/meeting builds).
   - `trial` — throwaway (`probe_key`), safe to delete.
   - `tutorial` — teaching material (`talent_steps`), must keep running.
5. A key is a **name, not a path**: `../x`, `a/b`, `Sun Hing`, `_x`, `9abc`, `x_v`, `x_v0`,
   `sunhing_1` and `sunhing_v01` are refused before anything is created, and `profile_dir()` proves
   the resolved path stays under `profiles/`. `services/ontology_publish.stage()` already refused
   absolute paths and `..`; a test now pins that too.

The registry is `backend/features/ontology/profiles/_versions.json` — committed, human-readable,
edited by hand only to correct a mistake.

## Current inventory (backfilled 2026-11-12)

| family | latest | chain | kind |
|---|---|---|---|
| `new_coldchain` | `new_coldchain_v6` | v3 → v4 → v5 → v6 | customer |
| `sunhing` | `sunhing_v1` | v1 | customer |
| `tpch` `retail` `logistics` `clinic` `abc` | the key itself | v1 | demo |
| `ebl_ops` `eff_ops` `meeting` `talent` | `_v1` / the key | v1 | demo |
| `talent_steps` | the key | v1 | tutorial |
| `probe_key` | the key | v1 | trial |

`new_coldchain_v7` is declared in `gates.json` but has no profile directory: a build that was
started and not finished. The number stays reserved, so the next cold-chain build is **v8** and
cannot collide with a half-built v7.

Inventory at any time:

```bash
cd backend && .venv/bin/python features/ontology/versioning.py
```

## Adding an ontology

```bash
cd backend
.venv/bin/python scripts/seeds/in/add_ontology_builder.py \
    --base chinook --datasource chinook --theme "音乐零售" --kind customer     # dry run
# … read the plan, then:
.venv/bin/python scripts/seeds/in/add_ontology_builder.py \
    --base chinook --datasource chinook --theme "音乐零售" --kind customer --apply
```

The script registers five artefacts (builder agent row, `gates.json` declaration, Settings →
Ontology row, `.env` variable, profile directory check) and **now also the version** in the
registry. Notes:

- A rebuild of a family **reuses the family's password variable** (`SUNHING_DB_PASSWORD`), because
  v2 reads the same database; inventing `SUNHING_V2_DB_PASSWORD` is how a deployment ends up with
  one blank password and a profile whose dsn cannot connect.
- The Settings row carries `version`, `kind`, `latest` and `superseded_by`. The workbench ignores
  those fields; an audit does not have to list directories to answer "which build is the customer
  running?".
- `--no-agent` registers everything **except** a per-key agent row. That is the path to the single
  builder template: the key is handed to the one agent instead of minting a row per customer.
- A re-run against the same `--key` is idempotent — it refreshes label/datasource and records
  nothing new. It never mints v2 of nothing.

## Gates

`backend/tests/test_ontology_versioning.py` (32 checks) pins: monotonic numbering across the three
sources, no reuse after a delete, the supersede chain, idempotent re-recording, the four kinds, the
refused key shapes, path containment, the publish path guard, registry round-trip and
corrupt-registry refusal, plus two checks against the **real** repository state (every family's
`latest` is its highest version; the next number for every existing family is free). Mutation-tested:
returning the highest existing number instead of +1, and dropping the supersede loop, each turn the
suite red.

## The single builder (agent 393)

`scripts/seeds/in/seed_ontology_builder_single.py` writes one agent, `Ontology Builder`:

- **no ontology in the row.** No `ontology_key` in `skill_params`, no key in the prompt. The key arrives
  in the conversation; the prompt says so in its second paragraph and forbids inventing one.
- **one database binding = the ontology server.** `config.database` is a custom block with
  `dbname=postgres` (the server's default database) and an encrypted password. That is what lets one
  agent serve many ontologies: `db_query(db_name="<key's db>", sqls=[...])` names the database per
  call, and `execute` uses `psql -d <db>`.
- **the tool superset** (12: adds `db_query` on top of the retired rows' 11), so measuring is one
  round-trip per batch and the rebuild path (`ontology_open`) exists.

`scope: conversation` in the skill's frontmatter is what makes this buildable. Before it,
`build-ontology-from-db` declared `ontology_key: required`, so `core/skills/params.resolve` returned a
problem and `assembly` raised — a keyless builder could not start at all ("set
config.skill_params[...]"), which is the opposite of asking the user. A conversation-scoped parameter is
never defaulted from the agent, never reconciled against `config.database` (one agent, many databases,
so there is no single right answer), and never required as a build condition. A per-key agent that
still supplies the values keeps rendering exactly as before —
`tests/test_skill_params_scope.py` pins both halves, including that a plain `required: true` elsewhere
still fails by name.

Proven with a real turn (local, 2026-11-12): agent 393 was asked, without acting, which ontology it
would write — it answered that it does not know yet and would read `profiles/<key>/_brief.md` +
`<key>_settings.json` once given the key, and that its connection defaults to `postgres` so it names the
database per call. A second turn had it measure `sunhing_kpi` with one `db_query` batch; its answer
(24 tables, 2 087 rows) matched an independent `count(*)` sum exactly.

## Retirement of the per-key rows

`scripts/seeds/in/retire_ontology_builders.py` (dry run by default, `--restore` to undo) set
`is_public=false` on 348, 349, 355, 376, 378, 379 and recorded
`config.superseded_by = "Ontology Builder"` + `config.retired = {at, reason, superseded_by}`. Nothing
was deleted: each row keeps its prompt and its key, so a key those rows alone knew about is still
readable, and one command puts them back. `--require-target` refuses to retire towards an agent that
does not exist.

## Not done yet

1. **Unify nothing else**: the six retired rows also lacked `ontology_key`-free prompts, but they are
   now invisible; if one is ever restored it should be re-pointed at the versioning rules first.
2. **Move the tool implementations** out of `backend/scripts/seeds/in/seed_ontology_*_tool.py` into
   `backend/tools/ontology_*.py` so a tool's code is not a string inside a seed script.
3. `new_coldchain_v7` needs a decision: finish it, or delete the declaration and keep the reserved
   number.
