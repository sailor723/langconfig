# Deploying the ontology feature (single box, Docker)

> The runbook for this directory. `docs/` is gitignored in this repository, so it lives with the
> deployment it describes.

The application is one image: the built frontend, the FastAPI backend, and the **ontology feature**
(compiler + gates + declarations). There is no second repository to clone and no second virtualenv —
`rdflib` is in the image's dependencies and the profiles ship inside
`backend/features/ontology/profiles/`.

```
browser ──► nginx ──► app:8765          (frontend + API + ontology compiler)
                      ├─ postgres        the app's own store
                      └─ ontology-postgres   the ontology databases (abc_coldchain, clinic_db, …)
```

**Nothing but the app is required.** Every page the UI shows — the dashboard, the graph view, the query
console, the actions page, the tutorial (including retail's eight hand-authored chapters and ABC's eight
training steps) — and every number in them is served and computed by the app process itself, at
`/api/ontology/{key}/…`. The five per-ontology workbench servers are a **development tool** now:
`deploy/workbench.yml` adds them for editing a profile's HTML in isolation, and nothing in the app starts
one. Measured with zero workbench processes running: `deploy_smoke` 25/25, `check_chapters` 209/209.

## 1. Configure

```bash
cp deploy/.env.example deploy/.env
$EDITOR deploy/.env        # POSTGRES_PASSWORD, DATABASE_URL, ONTOLOGY_DB_*
```

The ontology profiles declare their database as `${ONTOLOGY_DB_HOST:-127.0.0.1}` and
`${ONTOLOGY_DB_PORT:-5432}` (`retail`'s default is 15432 — it genuinely lives on another port). On a
laptop the defaults apply; here `ONTOLOGY_DB_HOST=ontology-postgres` is substituted at connect time by
`backend/features/ontology/compiler/dsn.py`. A variable the profile names but the environment does not
set is an **error at connect time**, not a blank host.

## 2. Bring it up

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f app
```

The ontology database starts empty. Two ways to fill it:

* `ONTOLOGY_SEED_DIR=./seed` — put SQL dumps in `deploy/seed/`; the container runs them once, on an
  empty volume;
* point `ONTOLOGY_DB_HOST` at an existing database (an RDS instance, a shared box) and skip the
  `ontology-postgres` service entirely.

## 3. Prove it, before a user does

```bash
python -m scripts.deploy_smoke --base http://<host>:8765
```

Twenty-five checks, each one a way this system has actually broken: the app answers · the frontend was
**built** · every ontology resolves its own profile · the dashboard renders panels and its opening
assessment parses · a question answers and a question refuses **by name** · a write verb's dry run with
impossible ids is not admitted · each ontology's graph page and tutorial are served **by the app** with no
absolute path pointing at a second origin · the gate suite runs on this box. Exit 0 or it names what is
missing. (`--skip-workbench` is accepted and ignored: there is no workbench to probe.)

Then the declarations themselves:

```bash
python -m scripts.ontology_gates          # 16 runs, one verdict
python -m scripts.ontology_gates --quick  # skip the slow NL/samples families
```

`check_chapters` is part of that suite for retail and ABC: it fetches each chapter and training page from
the running app, extracts the endpoints out of the page's OWN JavaScript, and calls every one of them
(209 checks). A chapter that grows a new `fetch()` is covered the day it is written.

A gate that reports `NOT RUN` is named and does not fail the run (an unrun gate is not a green one);
a family an ontology is not held to is **absent from `features/ontology/gates.json`**, and a known
failure is written there rather than hidden.

## 4. Operations that need to know about the compiler

**One worker.** `--workers 1` is deliberate: the compiler's profile state is process-wide and is
serialised by a lock inside the process (`services/ontology_runtime.py`). More workers would multiply
that state, not share it.

**Nothing depends on the ontology repository.** `ONTOLOGY_REPO` may point at the learning mirror for
the workbench pages; the app and the gates never need it. Every path inside the feature is relative
(`_paths.py`), which is what makes the image portable at all.

**A publish changes declarations inside the image.** Applying a staged publish edits
`backend/features/ontology/profiles/<key>/` and commits to the app's repository. In a container that
means the edit lives in that container's filesystem: mount the profiles from a volume if publishes must
survive a redeploy:

```yaml
    volumes:
      - profiles:/app/backend/features/ontology/profiles
```

**Rebuild after a declaration change** when the profiles are baked into the image rather than mounted.

## 5. What is not deployed (and why)

| not deployed | why |
|---|---|
| the ontology repository | it is a learning mirror; the compiler and the declarations live in the app |
| the workbench servers | the app compiles in-process AND serves the pages: graph, query, actions, tutorial, retail's eight chapters, ABC's eight training steps. They survive as a development tool (`deploy/workbench.yml`) |
| a second virtualenv | the compiler runs under the app's interpreter (M1/M2) |
| `serve_ui.py` framed pages | all of them are app endpoints now (`/api/ontology/{key}/page/…`, `/tutorial/chapter/{n}`, `/abct/{n}`); `check_chapters` calls every path they contain |
