# clinic — an ontology built by a DeepAgent, not by hand

This directory is the **artifact** of a build, kept as evidence rather than as a demo:
every file here was produced by a DeepAgent (agent row 348, `build-ontology-from-db` skill,
DeepSeek `deepseek-v4-flash`) from nothing but a database name. The human confirmed two
things (the model sketch and the definitions) and asked for three rounds of fixes; nothing
else was authored by hand.

| | |
|---|---|
| database | `clinic_db` @ 127.0.0.1:5432 (8 tables, 5,418 appointments, 6,443 treatment lines) |
| skill | `build-ontology-from-db` (langconfig `backend/skills/builtin/`) |
| agent config | `datasource: clinic` (host/user/credential from Settings → Databases, exported to the shell as `PG*`; the password never appears in the prompt or the transcript), plus a `workbench` contract (profile fields, gates to run) |
| produced | `ontology/01-structure.ttl`, `ontology/02-meaning.ttl`, `metrics_ext.ttl`, `clinic_settings.json`, `generated/*.md` |
| gates | `backend/features/ontology/gates/check_clinic.py` — C (ontology) · R (reasoning) · G (SQL guardrails) |

## Open it

It is already part of the app — no server to start:

```bash
# the app serves this ontology's pages itself (see deploy/README.md)
open http://127.0.0.1:8765/api/ontology/clinic/page/graph
```

For the DEVELOPMENT workbench of just this profile (optional, see `deploy/workbench.yml`):

```bash
cd backend/features/ontology/workbench
python3 serve_ui.py --settings ../profiles/clinic/clinic_settings.json --port 8096
```

The profile's own directory is where relative paths resolve, so `ontology_dir: "ontology"` and
`overlay: "metrics_ext.ttl"` point at this folder, not at the retail app's.

## Run the gates

```bash
# from backend/features/ontology/gates, with the interpreter that runs the app
<the app's .venv>/python check_clinic.py --profile ../profiles/clinic/clinic_settings.json
```

`check_clinic.py` covers the three families that matter here:

- **C — ontology**: every object class names a table and a primary key; every definition class
  resolves to one; every metric compiles **or refuses by name**; six metrics are reconciled
  against independently written SQL; five mutations (delete `:grain`, drop `:references`,
  misspell a formula column, duplicate a column, delete an axiom) must each turn it red.
- **R — reasoning**: each definition compiles and selects rows; the compiled predicate
  *entails exactly* the column-level statement of the same meaning; every sample question
  answers or refuses by name (and the set contains a refusal); **HermiT** must infer
  `:NoShowAppointment` for an individual whose only asserted facts are "an Appointment" and
  "status = no_show", and must lose that inference when the axiom is removed. The Ontop/SPARQL
  lane reports **NOT RUN** — this dataset has no R2RML mapping, so a green there would be a lie.
- **G — guardrails**: page cap, time bound (or refusal when the data is historical), plan
  budget, statement timeout, "a declared metric is never windowed", and "an empty window is
  reported, not silently zero".

Result at the time of archiving: **41 gates PASS, 0 FAIL, 1 NOT RUN by name (R5).**

The `aliases` block in the profile was added at archive time, after the samples gate showed
the matcher refusing 「按专科看预约数」和 「按患者城市看诊疗收入」: a Chinese dimension word is not
the same token as the property name it means, and the profile is where that belongs (the
skill's phase 8 says "per-profile aliases", not a global synonym list).

## What the agent got right, and what the gates caught

- It refused to invent definitions: `outstandingReceivable` is refused because the invoice
  grain and the payment grain cannot be subtracted without a business decision about which
  day the receivable is struck.
- It measured its thresholds (`0`, `0.2`, `1000`) and said which one still needs business
  confirmation.
- The repo compiler refused one metric the agent's own checker had passed:
  `claimDecisionDays` uses `EXTRACT(EPOCH FROM …)`, and `from` is not a column. That is
  recorded as a file-level refusal instead of being hidden — the agent's checker was weaker
  than the compiler, which is exactly why the compiler is the judge.
- `guard.py`'s statement timeout never bit: `SET LOCAL` outside a transaction is a no-op and
  psycopg2 reports `STATUS_IN_TRANSACTION` on an idle connection. Fixed in `guard.py`, and
  gate **G5** now proves it aborts.

## Provenance

| round | what it added |
|---|---|
| 1 (session `0986bea5…`) | phase 0 sketch, introspection, `01-structure.ttl`, `02-meaning.ttl`, `metrics_ext.ttl`, phase 9 refusal list |
| 2 (session `0986bea5…`) | compiler cross-check, threshold re-measurement, `generated/clinic_settings.json` |
| 3 (fresh session) | profile conformed to the workbench contract, gates run and reported |

The agent's own working files (`other/`: catalog, truth values, its checker and mutation
script) stayed in its workspace; what is archived here is the ontology, the profile and the
three human-readable deliverables.
