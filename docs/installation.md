# LangConfig — Installation & Team Sync

One command installs and one command updates: `seed_all.py` inspects the database and
decides which it is doing. This guide covers both, and how team changes travel between
machines.

**Which part do I need?**

| Situation | Read |
|---|---|
| The machine has never run LangConfig | **§2**, then **§3** |
| I am developing on the code | **§2 → Path A** |
| I received `langconfig.zip` | **§2 → Path B** |
| I changed agents/tools/settings; the team should get them | **§4** |
| Someone else's changes must reach an existing machine | **§5** |

---

## 1. What travels between machines — and what does not

| layer | how it moves | notes |
|---|---|---|
| **code** | `git clone` / `git pull` | `learning/` (the phase-9 GraphIndex package the chat path imports), `backend/skills/**` and all seed assets are tracked |
| **schema** | `alembic upgrade head` | the installer stamps head on a fresh database; an existing one needs a real upgrade |
| **agents** | `seeds/in/deep_agents_merge.sql` | **additive**: inserts only names that are absent |
| **tools** | `seeds/in/custom_tools_merge.sql` + `seeds/in/seed_builtin_tools.py` | **union** on `tool_id`; existing rows are never rewritten, so a teammate's edit — even to a built-in — survives (the `read_any_file` exception is in §7) |
| **models** | `seeds/in/models_seed.csv` + `seeds/in/upsert_model.py --preset deepseek-flash` | the CSV alone has no vision model |
| **skills** | `backend/skills/**` → FS→DB sync | three roots: `builtin/`, `personal/`, top-level `<id>/`; the file IS the artefact |
| **settings** | `seeds/in/settings_seed.json` → three-way merge | team values only; a key you changed locally is never overwritten |
| **credentials** | **never** — not exported, not committed, not applied | every `role="secret"` field is discovered from the settings schema and dropped on export (`models.api_keys.*` — LLM **and** web/search keys — plus `models.local_api_key`). Listed in the file's `__meta__.stripped` so you can audit what left |
| **per machine** | `.env`, API keys, `backend/outputs/` | secrets and workspaces are local by design |

**Deliberately NOT migrated:** `chat_sessions`, `conversation_archives`, the
LangGraph checkpoint tables, and uploaded document blobs. Each person keeps their
own history. This is also why a full `pg_dump` is the wrong tool — on one real
install **5.8 GB of a 6 GB database was `checkpoint_blobs`** (resumable graph
state), against ~1 MB of actual team knowledge (56 agents + 67 tools + 29 models
+ 43 skills).

---

---

## 2. Install a machine

### Path A — Local development install

For contributors. Requires **git**; everything else is covered in Path B below.

```bash
git clone <your-fork-url> langconfig
cd langconfig
npm install                      # frontend deps

cd backend
uv sync                          # creates backend/.venv from uv.lock, Python 3.13
cd ..

docker compose up -d postgres    # pgvector/pg16; host port = POSTGRES_PORT
cp env_example .env              # infrastructure only — DB, ports, workspace, tracing

cd backend
.venv/bin/python scripts/seeds/in/seed_all.py    # idempotent schema + seed
cd ..

bash start.sh                    # Postgres + backend :8765 + frontend :1421
```

Verify and test:

```bash
curl -s http://127.0.0.1:8765/api/chat/health
cd backend && .venv/bin/python -m pytest \
  --ignore=tests/test_neo4j_document_enrichment.py \
  --ignore=tests/test_pageindex_full_content_loader.py
npm run build                    # typecheck + production build
```

> **No API keys in `.env`.** Provider credentials are entered in the Settings UI and
> stored encrypted in PostgreSQL. The seed restores the model catalog and agents but
> **not** any credential, so the first-run wizard (or Settings → API Keys) is mandatory
> before an agent can answer. Path B step 6 covers the same rules for the zip install.

Differences from the team path below: you have git history and `node_modules` from
source, you do **not** need step 3 (unzip) below, and you seed an empty database rather than
restoring the team's committed baseline.

---


### Path B — Team install from the zip

Everything below, step 0 through step 9, is the detailed team-install path.

#### 0. What you receive

> Install LangConfig from the zip package on a fresh machine: PostgreSQL setup,
> uv, unzip, dependency sync, database seed (with your workspace), LLM API keys,
> health check, and startup.

`langconfig.zip` (≈31 MB) contains the full source tree minus secrets/build
artifacts (no `.env`, `node_modules`, `.venv`, `data`, `backend/outputs`, git
history). The database seed restores a machine-agnostic baseline: 56 deep
agents, 29 LLM models, 67 tools, 43 skills. **Your workspace paths and API keys
are added locally in the steps below — nothing machine-specific ships in the
zip.**

##### Prerequisites — Ubuntu (22.04 / 24.04)

A fresh Ubuntu server needs a few base tools before the steps below:

```bash
sudo apt update && sudo apt install -y unzip git curl ca-certificates lsof
```

`lsof` is not in a default Ubuntu/WSL image, and `start.sh` uses it to stop a previous backend or
frontend still holding `:8765` / `:1421` before starting a new one. Without it the port stays busy,
Vite refuses to fall back to another port (`strictPort: true`), and the only symptom is
`Error: Port 1421 is already in use` — so a re-run of `start.sh` looks like it half-started. It now
falls back to `fuser`, then `ss`, and says so when none is available; installing `lsof` is still the
recommended fix.

---

#### 1. PostgreSQL — install & setup

> ⚠️ **Do this BEFORE starting Postgres:** `docker compose` reads `.env` at
> compose time to pick the host port. If you start the container before
> creating `.env` (step 5), `POSTGRES_PORT` falls back to `5432` and the
> documented `5433` mapping won't apply. Recommended order: **create `.env`
> first (step 5)**, then start Postgres (this step) — or pass
> `POSTGRES_PORT=5433 docker compose up -d postgres` inline.

Pick **one** mode and note the three credentials — the whole app (backend,
Alembic, seeds, docker-compose, SQL agent) derives its connection from them.

| Item | Default | Where it's used |
|---|---|---|
| Database name | `langconfig` | `POSTGRES_DB` in `.env` |
| User | `langconfig` | `POSTGRES_USER` in `.env` |
| Password | `langconfig_dev` | `POSTGRES_PASSWORD` in `.env` |
| Host / Port | `localhost` : **5432** native, **5433** docker | `POSTGRES_PORT` in `.env` |

##### Option A — Docker (simplest, recommended for team)

```bash
# from the unzipped folder
docker compose up -d postgres
# container: langconfig-postgres on host port 5433 (→ container 5432)
# health: docker ps   →  "langconfig-postgres  0.0.0.0:5433->5432/tcp"
```

> **Docker not installed yet (Ubuntu)?**
> ```bash
> curl -fsSL https://get.docker.com | sudo sh      # installs docker engine + compose plugin
> sudo usermod -aG docker $USER                    # then re-login (or: newgrp docker)
> ```

> **pgvector**: bundled in the `pgvector/pgvector:pg16` image — no separate
> install needed. The extension is enabled by the app at boot
> (`CREATE EXTENSION IF NOT EXISTS vector`).

##### Option B — Native PostgreSQL 16 (macOS Homebrew)

```bash
brew install postgresql@16 pgvector   # pgvector required for embeddings
brew services start postgresql@16
# on :5432; create the role + database once (or let seed_all.py do it — it
# auto-creates role/db when the app user can connect as superuser):
psql postgres -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB SUPERUSER;"
psql postgres -c "CREATE DATABASE langconfig OWNER langconfig;"
```

##### Option C — Native PostgreSQL 16 (Ubuntu / WSL2)

**Ubuntu 24.04** — PostgreSQL 16 + pgvector are in the distro repos:

```bash
sudo apt install -y postgresql-16 postgresql-16-pgvector   # pgvector for embeddings
sudo service postgresql start
sudo -u postgres psql -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE langconfig OWNER langconfig;"
```

**Ubuntu 22.04** — ships PostgreSQL 14 and no pgvector package, so add the
official PGDG apt repo first (Postgres 16 + `postgresql-16-pgvector`), then
run the same commands as above:

```bash
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-pgvector
sudo service postgresql start
sudo -u postgres psql -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE langconfig OWNER langconfig;"
```

##### Option D — Native PostgreSQL 16 (RHEL / Rocky / Alma / CentOS Stream / Fedora, dnf)

```bash
# RHEL 9 / Rocky / Alma / CentOS Stream 9 (use EL-8 for RHEL 8-family):
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf -qy module disable postgresql
sudo dnf install -y postgresql16-server postgresql16 pgvector_16   # pgvector_16 = pgvector for PG16
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16
# on :5432; create the role + database once (or let seed_all.py do it):
sudo -u postgres psql -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE langconfig OWNER langconfig;"
```

> Fedora ships PostgreSQL 16 + `pgvector` natively:
> `sudo dnf install -y postgresql16-server postgresql16 pgvector` (skip the PGDG
> repo step; initdb + systemctl steps are the same).

##### Neo4j — optional, for the Cypher agent / Graph Studio

The `neo4j_agent` (Graph Studio) queries a Neo4j graph over **Bolt**. Skip this
section if you only use the SQL agent.

**Option 1 — Docker (local, free):**

```bash
docker run -d --name langconfig-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5-community
# web UI: http://localhost:7474   ·   bolt: bolt://localhost:7687
```

**Option 2 — Neo4j Aura (cloud, free tier):** create an instance in the Aura
console and use the Bolt URI + credentials it gives you.

**.env — the NEO4J_\* block** (values are already in `env_example`; add them to
your `.env`):

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
NEO4J_ENCRYPTED=false
NEO4J_URL=http://localhost:7474   # HTTP endpoint (document-index helpers)
```

> **Aura**: use the Aura-provided URI and set `NEO4J_ENCRYPTED=true`.

**Load a sample graph** (the agent's e2e tests use the Movies graph — `:play
movies` in the web UI loads the full dataset; a minimal seed for a quick check):

```bash
docker exec langconfig-neo4j cypher-shell -u neo4j -p password <<'CYPHER'
CREATE (m1:Movie {title:'The Matrix', released:1999}),
       (m2:Movie {title:'The Matrix Reloaded', released:2003}),
       (k:Person {name:'Keanu Reeves', born:1964}),
       (l:Person {name:'Lana Wachowski', born:1965}),
       (k)-[:ACTED_IN {roles:['Neo']}]->(m1),
       (k)-[:ACTED_IN {roles:['Neo']}]->(m2),
       (l)-[:DIRECTED]->(m1), (l)-[:DIRECTED]->(m2)
CYPHER
```

**Verify:**

```bash
cd backend && uv run python langgraph/test_neo4j_agent.py unit
# then open Graph Studio → neo4j agent → the DB dropdown shows the graph's labels
```

**Team seed — enterprise HR graph** (ships with this package:
`backend/scripts/seeds/neo4j-hr/neo4j.dump`, ≈19 MB — the knowledge graph the
`neo4j_agent` demos use: Person / Skill / Job / Domain / WorkType + KNOWS /
BUILT / LED …). Restore it into a fresh Neo4j container:

```bash
# 1. run the Neo4j container (match the source version — enterprise image):
docker run -d --name langconfig-neo4j-hr \
  -p 17475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/password \
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
  -v neo4j-hr-data:/data \
  neo4j:2025.10.1-enterprise

# 2. stop it, load the dump over the default database, start again:
docker stop langconfig-neo4j-hr
docker run --rm -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
  -v neo4j-hr-data:/data -v "$(pwd)/backend/scripts/seeds/neo4j-hr":/dumps \
  neo4j:2025.10.1-enterprise \
  neo4j-admin database load neo4j --from-path=/dumps --overwrite-destination=true
docker start langconfig-neo4j-hr

# 3. point LangConfig at it and verify:
#   NEO4J_URI=bolt://localhost:7688   (rest of the NEO4J_* block unchanged)
cd backend && uv run python langgraph/test_neo4j_agent.py unit
#   → Graph Studio shows Person/Skill/Job/Domain/WorkType labels
```

> **Version compatibility (important):** a Neo4j dump only restores into the
> **same or newer** server. The HR dump is from **2025.10.1**, so the container
> must run `neo4j:2025.10.1-enterprise` (or newer). The older `neo4j:5.x`
> (5.26) images reject it with *"The loaded database is of a newer version than
> the current binaries. Downgrade is not supported."*

> For the SQL-vs-Cypher side-by-side demo, load Northwind as a graph (or the
> Neo4j fraud demo) the same way — from your own Cypher files or an Aura dump.

> The role needs `CREATEDB` because `seed_all.py` step 1 creates the DB if
> missing, and step 10 creates the `chinook` sample DB for Graph Studio. It
> also needs **`SUPERUSER`** so the app can run `CREATE EXTENSION IF NOT EXISTS
> vector` (the pgvector extension) — the Docker image grants this to
> `POSTGRES_USER` automatically, which is why the native installs below must
> add it explicitly.

---

#### 2. Install uv (Python 3.13 manager)

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# then restart your shell or:  source ~/.local/bin/env   (path added automatically)

uv --version          # verify
```

Python **3.13+** is required (repo pins `>=3.13`). If your system python is
older, uv can fetch it:

```bash
uv python install 3.13
```

---

#### 3. Unzip the package

```bash
unzip langconfig.zip -d langconfig
cd langconfig
ls          # AGENTS.md  backend/  docker-compose.yml  docs/  package.json  src/  start.sh  scripts/ ...
```

---

#### 4. Sync Python dependencies (`uv sync`)

The project's Python manifest is **`backend/pyproject.toml`** (FastAPI, LangChain
1.x, LangGraph, deepagents 0.7.1, pgvector, Playwright, …). `uv sync` reads it
and creates `backend/.venv`.

```bash
cd backend
uv sync                 # creates .venv/ and installs all pinned deps
uv run python -c "import fastapi, langgraph, deepagents; print('deps OK')"
```

> `backend/requirements.txt` also exists as a pip fallback
> (`pip install -r requirements.txt`), but **`uv sync` is the canonical path**.
> Frontend deps are separate: `cd .. && npm install` (only needed for the UI;
> the backend API alone does not need it).

##### Node.js — required for the frontend UI

The UI needs Node **20.19+** (Vite 7 requirement). Install via nvm:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install 22
node --version && npm --version    # verify (node ≥ 20.19, npm ≥ 10)
```

Then, from the repo root: `npm install` (one-time) — needed before the
frontend can start (step 9).

---

#### 5. Configure `.env` BEFORE seeding — split by who owns the value

`.env` is the **bootstrap default** (read once at first boot). User-adjustable
runtime settings and API keys live in the DB, editable from the Settings panel.
Three sections, in order:

```bash
# backend/../.env  (repo root)
# Start from env_example (committed template), then edit three sections:

# ════ OPERATOR-ONLY (infrastructure — don't let users touch) ════
POSTGRES_HOST=localhost
POSTGRES_PORT=5433          # docker; use 5432 for native
POSTGRES_DB=langconfig
POSTGRES_USER=langconfig
POSTGRES_PASSWORD=langconfig_dev
# Generate once with:  openssl rand -hex 32   then paste the 64-hex output here
API_KEY_ENCRYPTION_KEY=PASTE-THE-64-HEX-OUTPUT-OF-OPENSSL-RAND-HERE
ENVIRONMENT=development
TEST_DATABASE_URL=postgresql+asyncpg://langconfig:langconfig_dev@localhost:5433/langconfig_test
SQL_POSTGRES_DB=chinook
GOOGLE_REDIRECT_URI=http://localhost:8765/api/auth/google/callback
OLLAMA_BASE_URL=http://localhost:11434
SQL_ECHO=false
RATE_LIMIT_CLEANUP_INTERVAL=300
# Neo4j (optional — Cypher agent / Graph Studio; see step 1 "Neo4j"):
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
NEO4J_ENCRYPTED=false

# ════ USER-ADJUSTABLE (bootstrap defaults — UI overrides at runtime) ════
# The values here seed the 'runtime' settings namespace on first boot.
# Edit here to change the bootstrap default; the Settings panel edits the
# live DB value and always wins once the team has set anything.
LANGCONFIG_WORKSPACE_ROOT=backend/.workspace_data
STORAGE_MODE=db
OLLAMA_EMBED_MODEL=nomic-embed-text:latest
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=langconfig
BACKUP_DIR=./backups
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
ANALYSIS_RECURSION_LIMIT=1000
ANALYSIS_DASHBOARD_TIMEOUT=600
ANALYSIS_CHAT_TIMEOUT=120
MAX_EXECUTION_HISTORY_PER_WORKFLOW=100
EXECUTION_HISTORY_RETENTION_DAYS=90
AUTO_CLEANUP_EXECUTION_HISTORY=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=1000
PERFORMANCE_MONITORING_ENABLED=true
SLOW_REQUEST_THRESHOLD_MS=1000
LOG_SLOW_QUERIES=true
SLOW_QUERY_THRESHOLD=1.0
LOG_ALL_REQUESTS=false

# ════ API KEYS — DO NOT PUT IN .env ════
# All secrets live in the encrypted models.api_keys settings document
# (Settings → Models, or via the first-run wizard). API_KEY_ENCRYPTION_KEY
# above is the Fernet master key that encrypts them at rest.
```

### Workspace parameter — where the per-agent folder lives

The folder the team actually cares about is the **per-agent output folder**
(where agents write files). It is resolved **per chat session**
(`WorkspaceManager.resolve_agent_workspace`), in priority order:

1. **User-defined** — `deep_agent_templates.workspace_path` (per agent);
   absolute paths used as-is, relative paths anchored to the vault root.
2. **Vault-scoped** (session bound to a project, `chat_sessions.project_id`) —
   `{workspace_base}/{vault_key}/agents/{agent_key}/`, where `vault_key` is the
   project's slugified name and `agent_key` the agent's slugified name.
3. **Legacy default** — `{workspace_base}/agents/agent_{id}/` when the session
   has no project binding.

The identity (system prompt + AGENTS.md/CLAUDE.md) is **re-baked with the
session's resolved root on every chat** (docs/system-architecture.md §16.10),
so an agent bound to a project reports the vault-scoped path. The seed and the
backfill run project-agnostic, so they bake the legacy default unless you set
`workspace_path`.

The team can steer the layout in three ways:

1. **Per-agent `workspace_path` in the DB** (the canonical override). Set
   `deep_agent_templates.workspace_path` to an absolute path (or a relative
   path anchored to the workspace settings document's base). Editable from the
   Settings panel for each agent.

2. **Bulk-update via the backfill script** (`scripts/seeds/in/backfill_agent_identity.py`):
   re-bakes every agent's identity + docs under a given root with the
   `agent_{id}/` segment — the only way to change the resolved filesystem
   layout for all agents at once (no project binding → legacy layout under
   that root).

3. **`.env` value `LANGCONFIG_WORKSPACE_ROOT`** is **NOT** the per-agent root.
   It's read by `services/agents_md_service.py` to locate the project-level
   `AGENTS.md` directory (under `<root>/{project_id}/`). It is *not*
   used by the per-agent workspace resolution, the seed, or the backfill.

**In short**: the answer to "do I set it in `.env` with seed_all.py?" is **no** —
the seed always uses the legacy default unless you explicitly set the per-agent
`workspace_path` column. At runtime, sessions bound to a project automatically
resolve the vault-scoped folder (`{vault_key}/agents/{agent_key}/`, §16.10);
override via `workspace_path` or re-run the backfill.

---
---

#### 6. Apply LLM API keys (in the DB, not in `.env`)

**All API keys live in the database** (`models.api_keys` settings document),
encrypted at rest with `API_KEY_ENCRYPTION_KEY` (the Fernet master key in
`.env` above). `.env` is no longer a source for API keys — the Settings panel
(or the first-run wizard) is the only edit path.

Resolution order (`config.py::get_api_key_from_db`):
1. **PostgreSQL** — the `models.api_keys` field (set via Settings → Models).
2. **`.env`** — kept only as the bootstrap default on first boot (deprecated).

For a team install, the Settings UI is the only path:

1. **First-run wizard in the UI** — open `http://localhost:1421` after startup,
   the Setup wizard prompts for API key + workspace.
2. **Settings → Models** after boot — add provider keys (OpenAI / Anthropic /
   DeepSeek / Google / MiniMax / Tavily …).

> The shipped `env_example` has no API keys (per the "API KEYS — DO NOT PUT IN
> `.env`" section above). For a legacy `.env` containing old keys, run the
> one-shot migration to move them to the DB: `uv run python
> scripts/import_api_keys_to_db.py` (idempotent, dry-run supported).
>
> Which key(s) you need depends on the models your agents use. The seeded agents
> default to Anthropic (`claude-sonnet-4-5`) / DeepSeek models — at minimum add
> the provider key matching your default model, e.g. `ANTHROPIC_API_KEY` or
> `DEEPSEEK_API_KEY` (Settings → Models).

---


#### 8. Pre-start health check

`scripts/health_check.sh` verifies Postgres, the API, DB connectivity and
seeded data **before** you start the full stack:

```bash
bash scripts/health_check.sh                 # default backend :8765
BACKEND_PORT=8799 bash scripts/health_check.sh   # custom port
```

Expected output (all ✅):

```
── [1/4] PostgreSQL ───────────────   ✅ PostgreSQL accepting connections on :5433
── [2/4] Backend API ───────────────   ✅ Backend reachable on :8765
── [3/4] Detailed health ──────────    overall: healthy | database: healthy
── [4/4] Seeded data ──────────────    ✅ deep agents in DB: 44
✅ ALL CHECKS PASSED — ready to run:  bash start.sh
```

If it fails, it prints the fix for each step (start Postgres → seed → retry).

> Note: the script needs the backend **already running** to check steps 2–4.
> First boot: start backend once (`bash start.sh --be`), run the check, then
> `bash start.sh` for the full stack.

---

#### 9. Start the full stack

```bash
bash start.sh
```

| Process | URL | Notes |
|---|---|---|
| Backend (FastAPI, 2 workers) | `http://localhost:8765` | Swagger at `/docs` |
| Frontend (Vite/React) | `http://localhost:1421` | VS Code-style IDE shell |
| PostgreSQL | `:5433` (docker) / `:5432` (native) | |

Useful variants:

```bash
bash start.sh --be    # backend only (frontend keeps running)
bash start.sh --fe    # frontend only
```

First login: the Setup wizard asks for your API key + workspace path — the
workspace you enter here should match `WORKSPACE_ROOT` from step 5 so the
identity baked into agents points at the same folders the runtime uses.

---

---

## 3. Seed the database — install and update alike

There are two ways in, and they are not the same. Pick by what the machine already
has, not by what you want it to have.

### A machine that already has an install

Use the update path in **§5** — same command, and the same command again on every
future update. In short:

No `git clone`, no `cp env_example .env`, no `docker compose up`: it already
has a working repository, `.env`, a running Postgres and a venv. Copying `.env`
would overwrite a working one — including the `API_KEY_ENCRYPTION_KEY` that its
stored provider keys are encrypted with.

```bash
cd /path/to/langconfig
git status                # confirm nothing local is half-finished
git pull --ff-only        # refuses to guess if the machine has diverged

cd backend
uv sync                                   # bring the venv to the new uv.lock
.venv/bin/python -m alembic upgrade head  # BEFORE seeding — see the warning below
.venv/bin/python scripts/seeds/in/seed_all.py
.venv/bin/python scripts/seeds/verify/smoke_test.py    # §6
```

> **Why `alembic upgrade head` has to come first.** Step 3 of `seed_all.py` runs
> `alembic stamp head` **unconditionally**: it *records* the revision instead of
> applying migrations. That is correct for a fresh database, which cannot replay
> the 001–021 chain, and wrong for an existing one — seed first and any migration
> the update brought is marked applied without ever having run, leaving the schema
> silently behind the code. `upgrade head` applies whatever is pending and makes
> the stamp a no-op.

Nothing of theirs is lost: their agents, tools, skills, chat sessions and any
setting they changed themselves come through, and a name or `tool_id` clash keeps
**their** version (§7 lists the only two exceptions).

### A fresh machine

Prerequisites, clone, database and dependencies first (§2, then Path B), then:

```bash
cd backend
.venv/bin/python scripts/seeds/in/seed_all.py
```

Either way, seeding without pulling (or cloning) first just re-applies the
snapshots the machine already had.

Idempotent and **additive**. It is safe to re-run, and safe to run on a database
that already has a teammate's work in it. The steps, in the order `seed_all.py`
runs them (it labels them `[n/10]`, with two half-steps — `4b` and `8.5`):

1. `init_server()` — create the role and database if missing
2. `init_db()` — 48 tables + the pgvector extension
3. schema version — **auto-detected**: a database with no recorded revision is
   *stamped* at head (step 2 just built its schema from the ORM models), one that
   records a revision is *upgraded*, applying whatever is pending. Same command
   either way; no flag, because forcing `upgrade` on a fresh database would
   collide with the tables step 2 created
4. `seed_settings.py` — default settings documents, **missing namespaces only**
5. team settings — the exported `settings_seed.json` merged three-way over those
   defaults (§3). Without this step a value you changed in the UI never reaches
   anyone, because step 4 only fills namespaces that are still empty
6. `seed_models.py` + `upsert_model.py --preset deepseek-flash` — catalog
7. `seed_search_providers.py` — 6 search backends
8. tools — `custom_tools_dump.sql` **only into an empty table**; when the table
   already has rows, `seed_builtin_tools.py` adds just the built-ins that are
   missing and leaves every existing row alone. Then the **additive**
   `custom_tools_merge.sql`, then `scripts/seeds/in/seed_read_any_file_tool.py` (the reader
   tool sits outside `seeds/` because it needs trusted code — filesystem,
   tesseract, the reader graph; it is also the one row the seed **upserts in
   place**, so an edit to `read_any_file` specifically is reverted)
9. agents — **additive** `deep_agents_merge.sql`
10. identity backfill — resolves each agent's real workspace and bakes identity
11. skills — FS → DB sync; chinook sample DB (best-effort)

**The guarantee:** agents and tools are united on their identity
(`name` / `tool_id`). A teammate with 5 tools, where 3 match yours, ends with
8 — and their 3 keep **their** version. Nothing is truncated, renamed or
rewritten. The only destructive path is the explicit flag:

```bash
.venv/bin/python scripts/seeds/in/seed_all.py --replace   # TRUNCATEs agents + tools,
                                                       # and CASCADE takes their chat sessions
```

> **`--replace` resets to the maintained baseline.** It truncates, then restores the
> **merge** files, so a reset lands on the same 56 agents / 67 tools as a default
> seed. It used to restore the explicit-id dumps (`deep_agents_dump.sql` /
> `custom_tools_dump.sql`), which had drifted to 44 agents — 12 short. Those dumps
> are now legacy and reported as such by `export_baseline.py --check`. See
> [`installation.md`](installation.md#--replace-resets-to-the-maintained-baseline).

Optional, for a test run that must not touch real workspaces:

```bash
WORKSPACE_ROOT=/tmp/langconfig-ws .venv/bin/python scripts/seeds/in/seed_all.py
```

`WORKSPACE_ROOT` here is **not** the `.env` variable from §2 — that one is the
project-level `AGENTS.md` root. This is a one-shot override that `seed_all.py`
forwards to the identity backfill as `--workspace-root`, changing where the seeded
agents' workspaces are baked for this run only. Leave it unset to bake the
per-agent paths already in the seed (each agent's `workspace_path`).

---

### What is in `scripts/seeds/`

Everything the seed installs is a file here. Nothing is generated at install time.

The folder is split by role, and `_seedpaths.py` is the single place that knows the
layout:

```
scripts/seeds/
├── _seedpaths.py    path constants shared by every script (the anchor)
├── in/              the seed-IN entrypoint, its artifacts, and their loaders
├── out/             export a live DB -> a committable artifact
└── verify/          tests, a report, and the two-machine rehearsal
```

| File | Role |
|---|---|
| **`in/`** | |
| `in/seed_all.py` | entrypoint — runs the 10 steps, idempotent, add-only by default |
| `in/seed_settings.py` + `in/settings_seed.json` | default settings documents; the JSON is the **team** layer, merged three-way |
| `in/seed_models.py` + `in/models_seed.csv` | the 29-model catalog (9 providers); `upsert_model.py` adds the vision model |
| `in/seed_search_providers.py` | the 6 search backends (Tavily, DuckDuckGo, Wikipedia, Exa, Brave, SerpApi) |
| `in/seed_builtin_tools.py` + `in/custom_tools_merge.sql` | built-in tools; the merge unions 67 tools by `tool_id` |
| `in/deep_agents_merge.sql` | 56 agents, one `INSERT` each, guarded by `WHERE NOT EXISTS (name)` |
| `in/seed_read_any_file_tool.py` | the `read_any_file` builtin (trusted code: OCR + one vision call) |
| `in/upsert_model.py` | adds or edits a single model row; `--preset deepseek-flash` is the vision model |
| `in/backfill_agent_identity.py` | bakes each agent's real id, workspace and AGENTS.md into its prompt/docs |
| `in/drop_projects_segment.py` | one-time schema migration applied by the seed |
| `in/chinook_dump.sql` | sample Chinook data for the Graph Studio SQL agent |
| `in/neo4j-hr/` | Neo4j HR seed (JSON + `import_hr_seed.py`); the 19 MB `neo4j.dump` is local-only |
| `in/*_dump.sql` | explicit-id snapshots — **legacy**, no longer restored by `seed_all` |
| **`out/`** | |
| `out/export_baseline.py` | regenerates every exported artifact; `--check` reports staleness (exit 1) |
| `out/export_agents_merge.py`, `out/export_tools_merge.py`, `out/export_settings.py` | the three exporters it drives |
| **`verify/`** | |
| `verify/verify_additive_seed.py` | a teammate's own agents and chat sessions survive |
| `verify/verify_tools_union.py` | the tool union arithmetic, on the real 67-tool file |
| `verify/verify_settings_merge.py` | three-way settings merge outcomes |
| `verify/verify_untouched.py` | a teammate's rows stay byte-identical |
| `verify/check_tool_overlap.py` | reports same-tool-different-id candidates (a report, not a test) |
| `verify/verify_tools.py` | ad-hoc report: which agents carry a given tool |
| `verify/smoke_test.py` | post-install smoke test — run after `seed_all.py` and after starting the backend |
| `verify/rehearse_team_migration.py` | rehearses the whole two-machine delivery |

Each `verify_*` script owns the scratch database it asserts on (it truncates first), so
they can be run in any order — all four need `POSTGRES_DB=langconfig_seedtest`.

Two things to know about `settings_seed.json`: secrets are **stripped** before it
ships (`models.api_keys`, `workspace.workspace_path`), so no API key ever arrives
in the seed; and LangSmith tracing is seeded **off**, because `langsmith_api_key` is
one of the stripped secrets — tracing-on without a key only produces unauthenticated
401s. Enable it in Settings after adding a key.

#### `--replace` resets to the maintained baseline

`--replace` truncates `deep_agent_templates` (CASCADEs to their chat sessions) and
`custom_tools`, then restores the **merge** files — so a reset lands on exactly the
same 56 agents / 67 tools that a default install produces.

The older behaviour restored the explicit-id **dumps** instead, and those had drifted:

| | explicit-id dump | merge (used by both paths now) |
|---|---|---|
| agents | 44 | **56** |
| tools | 57 | **67** |

Restoring the dump alone short-changed the reset by 12 agents, and restoring dump +
merge overshot to 58 by unioning in two retired agents. `export_baseline.py` reports
the dumps as legacy so the drift stays visible:

```bash
uv run python scripts/seeds/out/export_baseline.py --check
```

`seed_all.py` no longer reads `deep_agents_dump.sql`. The document is small and
reversible, which is why the file is kept — not because it is used.

Verify the result (works regardless of the workspace root you chose):

```bash
uv run python -c "
from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate
db = SessionLocal()
a = db.query(DeepAgentTemplate).filter_by(id=1).first()
sp = (a.config or {}).get('system_prompt','')
print('identity:', '## Identity' in sp, '| agent_id baked:', 'Agent ID**: 1' in sp, '| no placeholder:', 'WORKSPACE_BASE' not in sp and '{{' not in sp)
db.close()
"
# expect: identity: True | agent_id baked: True | no placeholder: True
```

> To change the workspace later, re-run only the backfill:
> `uv run python scripts/seeds/in/backfill_agent_identity.py --workspace-root <new>`

---

---

## 4. Publish team changes — seed out, commit, push

**Agents and tools live in Postgres, not in git.** Creating or editing one in the
UI changes nothing in the repository, so the snapshots under
`backend/scripts/seeds/` are the only thing that carries them to a teammate — and
a stale snapshot fails *silently*: their `seed_all.py` just adds nothing new.

The order is always **seed out → commit → push → they pull → they seed**. Seeding
out is what puts your database into the repo, the commit records it, and the push
is what actually delivers it: git is the only channel between the two machines, so
a commit that is never pushed reaches nobody. Nothing reaches their database until
they run `seed_all.py` (§5). Skipping the seed out and committing anyway ships the
*previous* state, which looks like a successful migration that delivered nothing.

```bash
cd backend

# 1. SEED OUT — first ask whether you are due, then photograph the database
.venv/bin/python scripts/seeds/out/export_baseline.py --check   # reads only; exit 1 = you are due
.venv/bin/python scripts/seeds/out/export_baseline.py           # writes the snapshots

# 2. COMMIT — every artefact it wrote, or the leg you forgot ships stale
#    in/ holds the merge .sql files AND settings_seed.json; skills are their
#    own artefact (the SKILL.md files ARE the data), so they are added too.
git add backend/scripts/seeds/in/ backend/skills/
git commit -m "chore(seeds): refresh team baseline"

# 3. PUSH — until this runs, the snapshot exists only on your machine
git push

# 4. THE TEAMMATE — pulls that commit, then seeds (§5). Nothing before their
#    seed has touched their database.
```

Run `--check` first: it only reads, so it is the cheap way to answer "do I owe the
team a seed?" at any time.

### No credential leaves the machine

Two independent guards, because the artefacts are of two different kinds:

**Settings — scrubbed from the schema.** `export_settings.py` drops every field the
namespace schema marks `role="secret"`, rather than consulting a hand-written list:
LLM keys, web/search keys (Tavily, Serper, Exa, Brave), LangSmith, the Google client
secret, Slack/Discord webhook URLs **and** `models.local_api_key`. What was removed is
listed in `__meta__.stripped`, so the diff shows it. The schema is the reason a new
provider field cannot be forgotten — the earlier list-based version stripped
`models.api_keys` and shipped `models.local_api_key` one field away.

**Agents and tools — refused, not scrubbed.** Those exports carry *your* prose and
code (system prompts, `AGENTS.md`, a tool's `implementation_config`), so there is no
schema to consult. Instead `_secretscan` looks for credential shapes (`sk-…`,
`tvly-…`, `AIza…`, `AKIA…`, `ghp_…`, `xox…`, webhook URLs, Fernet blobs, JWTs,
`Bearer …`, and `api_key: "…"` assignments) and the exporter **refuses to write**
until it is clean — including on the `--stdout` path, since printing is how a value
reaches a paste or a log.

```bash
.venv/bin/python scripts/seeds/out/export_baseline.py --check   # sweeps every artefact
```

The check also sweeps the whole published set (hand-maintained CSV, legacy dumps) and
reports `credentials` in its STALE list if anything matches. When a tool genuinely
needs a token: **put it in Settings → API Keys**, which is never exported. If you must
ship anyway, `--redact` writes the file with the value replaced by
`***REDACTED-BY-SEED-OUT***` — and says plainly that the affected row will not work
for teammates until the credential moves.

A teammate therefore always enters their own keys: the seed carries the catalog, not
the credentials. It catches both kinds of drift: a **new** row (counts
differ) and an **edited** row (counts identical, bytes differ) — the second is why
it compares the regenerated file byte-for-byte rather than counting rows.

Both `git add` paths matter: the export rewrites `settings_seed.json` as well as
the two `.sql` snapshots, so a `*.sql`-only glob leaves the settings leg behind —
committed as stale, and silently, because the file simply does not appear in the
diff.

It covers four legs:

| leg | artefact | checked how |
|---|---|---|
| agents | `deep_agents_merge.sql` | row count, then bytes |
| tools | `custom_tools_merge.sql` | row count, then bytes |
| settings | `settings_seed.json` | namespace count, then bytes |
| skills | the `SKILL.md` files themselves | a DB-only skill, or a file not committed |

**Settings** are exported by `scripts/seeds/out/export_settings.py`, which strips
`models.api_keys` (encrypted with *your* `API_KEY_ENCRYPTION_KEY`) and any
absolute path such as `workspace.workspace_path`, and skips `general` and
`onboarding` — one is per-person cosmetic, the other would let a teammate's
install skip the setup wizard that asks for their API keys. `seed_all.py` step 4b
applies it with a **three-way merge** against the code defaults: a key nobody
touched adopts the team value, a key somebody changed themselves is left alone.

**Models remain the one leg with no export path** — a hand-maintained CSV plus the
`deepseek-flash` preset in `upsert_model.py`. A model added through the UI does not
travel.

### Making it unmissable (opt-in)

A pre-commit guard lives in `.githooks/pre-commit`. Enable it **on the machine
that owns the baseline** — not on a teammate's clone, where the guard would read
*their* database and treat their own agents as drift:

```bash
git config core.hooksPath .githooks
git config langconfig.seedGuard true            # stop a commit with a stale snapshot
git config langconfig.seedGuardMode auto        # ...or regenerate + stage it for you
```

With `auto`, committing after creating an agent simply includes the refreshed
snapshot. Bypass deliberately with `git commit --no-verify`.

> **Caveat, learned the hard way:** the guard exports from whatever database the
> environment points at. A run with `POSTGRES_DB=<something else>` wrote *that*
> database's agents into the committed snapshot; it was caught and reverted, but
> it is why the guard is opt-in and why the hook never regenerates on a machine
> that does not own the baseline.

Both exporters strip machine paths to `WORKSPACE_BASE/…`, which
`core/agents/identity.py` rewrites at run time and step 9 re-bakes per install.

**Convention that keeps the union clean:** shared tools use the catalog's
canonical `tool_id`, so the merge recognises them and teammates get your
updates; a personal variant gets a deliberately different id and lives alongside.
If two tools *are* the same thing under different ids, the merge cannot know
(names are editable labels — matching on them would silently drop real tools).
`scripts/seeds/verify/check_tool_overlap.py` reports those candidates on demand, and the
Tool Library is where a user deletes the redundant one.

---

## 5. Update an existing machine — pull, then seed

```bash
cd /path/to/langconfig
git status                  # confirm nothing local is half-finished
git pull --ff-only          # refuses to guess if the machine has diverged

cd backend
uv sync                                   # venv to the new uv.lock
.venv/bin/python scripts/seeds/in/seed_all.py
.venv/bin/python scripts/seeds/verify/smoke_test.py
```

> **Why there is no separate `alembic upgrade head` step.** `seed_all.py` reads
> `alembic_version` first. A database with **no** recorded revision is *stamped* at
> head — correct, because step 2 has just built the schema from the ORM models and
> the 001..0xx chain cannot be replayed on top of it. A database that **does** record
> a revision is *upgraded*, applying whatever is pending. This replaces the old
> unconditional stamp, which on an existing database marked pending migrations
> applied without running them and left the schema silently behind the code.

Nothing of theirs is lost: their agents, tools, skills, chat sessions and any setting
they changed themselves come through, and a name or `tool_id` clash keeps **their**
version (§7 lists the only two exceptions).
---

## 6. Verify

```bash
cd backend
.venv/bin/python scripts/seeds/verify/smoke_test.py                 # database + seed + API
.venv/bin/python scripts/seeds/verify/smoke_test.py --chat 112       # also one real agent turn
```

It checks, and prints what it saw for each:

- **database** — reachable, and the row counts of agents / tools / models /
  skills / settings / projects
- **seed content** — agents and tools present; ≥25 models; **a vision model
  exists**; **`deepseek-flash` carries `capabilities.vision`** (i.e. the preset
  step ran); **`read_any_file` seeded**; skills indexed; settings seeded;
  the configured workspace directory exists
- **API** — `/api/chat/health`, `/api/settings/setup-status`,
  `/api/deepagents/`, `/api/settings/models`
- **live turn** (with `--chat`) — creates a session and gets an answer, which
  exercises credentials, the agent build and the model route

Reference run on this install (condensed — the script prints one line per check):

```
[1] database        PASS  agents=56, tools=67, models=29, skills=43, settings=8
[2] seed content    PASS  9 checks (vision models: 18, read_any_file: 1 row)
[3] backend API     PASS  4 endpoints HTTP 200
=== 15 passed, 0 failed, 1 skipped ===
```

The one skip is the live turn; pass `--chat <agent_id>` to include it.

Manual equivalents, if you prefer:

```bash
curl -s localhost:8765/api/chat/health
curl -s "localhost:8765/api/chat/sessions?limit=5"
# a real turn through the UI: open http://localhost:1421/#/chat?agentId=112
```

Optional regression proof that the seed cannot clobber a teammate (needs a
scratch database, never touches the configured one):

```bash
createdb -h localhost -p 5433 -U langconfig langconfig_seedtest   # or psql -c "CREATE DATABASE …"
POSTGRES_DB=langconfig_seedtest .venv/bin/python scripts/seeds/verify/verify_additive_seed.py
POSTGRES_DB=langconfig_seedtest .venv/bin/python scripts/seeds/verify/verify_tools_union.py
```

Each script refuses to run unless the URL contains `langconfig_seedtest`, clears
the tables it is about to make claims about, and applies the **real** generated
seed at the end. So the two commands work in either order, repeatedly, in the one
scratch database. Each prints `ALL CHECKS PASSED` — the first proves a teammate's
own agent, tool and chat session survive (including a name clash, where *their*
version wins), the second proves the tool count arithmetic `5 + 3 = 8`.

For the whole loop rather than the merge SQL alone — creator machine, seed out,
commit, a teammate clone that pulls it, a teammate database already full of their
own work — one command makes everything it needs under `/tmp`, including both
clones and both databases:

```bash
.venv/bin/python scripts/seeds/verify/rehearse_team_migration.py
```

It asserts the two guarantees this document otherwise only states: that what a
teammate installs is **identical** to what the owner has, and that across two
deliveries every one of their rows (agents, tools, a chat session, and a setting
they changed themselves) comes through byte-identical — while a name clash and a
`tool_id` clash keep **their** version. It also re-checks the real database and
the real working tree at the end, so it cannot pass by having damaged the thing it
was measuring.

### On a real machine, after an update

`smoke_test.py` only asserts that things are **present** (`> 0`, `>= 25`) — it says
nothing about whether the person's own work survived, which is the half of the
promise that matters on a machine that already had an install. This reads the
baseline out of the merge files, subtracts it, and reports what is left. Read-only,
safe anywhere:

```bash
cd backend && .venv/bin/python - <<'EOF'
import re
from pathlib import Path
from db.database import engine
from sqlalchemy import text

base = Path("scripts/seeds")
agents = set(re.findall(r"WHERE name = '((?:[^']|'')*)'", (base / "deep_agents_merge.sql").read_text()))
tools = set(re.findall(r"WHERE tool_id = '([^']+)'", (base / "custom_tools_merge.sql").read_text()))

with engine.connect() as c:
    q = lambda s: c.execute(text(s)).scalar()
    rows = lambda s: [r[0] for r in c.execute(text(s))]
    n_a, n_t = q("SELECT count(*) FROM deep_agent_templates"), q("SELECT count(*) FROM custom_tools")
    mine_a = [n for n in rows("SELECT name FROM deep_agent_templates ORDER BY name") if n not in agents]
    mine_t = [t for t in rows("SELECT tool_id FROM custom_tools ORDER BY tool_id") if t not in tools]
    dup_a = q("SELECT count(*) FROM (SELECT name FROM deep_agent_templates GROUP BY name HAVING count(*)>1) d")
    dup_t = q("SELECT count(*) FROM (SELECT tool_id FROM custom_tools GROUP BY tool_id HAVING count(*)>1) d")
    stale = q("SELECT count(*) FROM custom_tools WHERE tool_id = 'write_file'")

print(f"baseline in the repo : {len(agents)} agents, {len(tools)} tools")
print(f"this database        : {n_a} agents, {n_t} tools")
print(f"kept from before     : {len(mine_a)} own agent(s), {len(mine_t)} own tool(s)")
if mine_a: print(f"   own agents        : {mine_a}")
if mine_t: print(f"   own tools         : {mine_t}")
print(f"duplicates           : {dup_a} agent names, {dup_t} tool ids")
print(f"stale write_file row : {stale}   (must be 0)")
EOF
```

What to expect on a teammate's machine: totals at least the baseline's, their own
names and ids listed under "kept from before", `0` duplicates in both, and `0` for
the stale row. On the machine that owns the baseline the two "kept from before"
counts are legitimately `0` — everything there *is* the baseline.

---

## 7. Footguns

- **Exactly two things of a teammate's can be rewritten, and neither is their own
  work.** `custom_tools_merge.sql` and `deep_agents_merge.sql` never touch an
  existing row, and `seed_builtin_tools.py` only adds built-ins that are missing —
  so an edit to a built-in survives. The exceptions:
  - **`read_any_file`** — its own script (`scripts/seeds/in/seed_read_any_file_tool.py`)
    upserts the row in place, so an edit to that one tool is reverted;
  - **a skill that also ships in the repo** — the FS→DB sync overwrites an
    existing row whenever the repo's `SKILL.md` is *newer* than the row's
    `file_modified_at`, so a teammate's edit is kept only while their copy is the
    newer one. A skill that exists **only** in their database is never touched.
- **`--replace` is destructive** — truncates agents and tools; the CASCADE also
  removes those agents' chat sessions.
- **A seed against a scratch database is not passively safe.** Step 10's identity
  backfill falls back to the `workspace.base_dir` **settings document** when
  `WORKSPACE_ROOT` is unset, and that fallback can MOVE real directories under it
  — so `POSTGRES_DB=something_else seed_all.py` can still rearrange *this*
  machine's agent folders. Always pass `WORKSPACE_ROOT=/tmp/<scratch>-ws` when
  seeding a database that is not the one you are actually working in.
- **The empty-table dump can contradict the live database.** `custom_tools_dump.sql`
  is a `pg_dump` block with explicit ids that applies *only* when `custom_tools`
  is empty — the fresh-install path — while the merge is what keeps an existing
  install current. They have already drifted once: the dump still carried the
  `write_file` row after it was deleted from the live database and from
  `SEEDABLE_TOOL_META`, so the owner had 67 tools and every new teammate got 68.
  `scripts/seeds/verify/rehearse_team_migration.py` now asserts that a teammate's fresh
  install equals the owner's, which is what caught it.
- **Port confusion** — `5433` via docker-compose, `5432` native. `.env` decides;
  compose reads it at start time.
- **Indexing fails without Ollama** — document indexing needs the embedding
  model; chat does not.
- **Checkpoint growth** — `checkpoint_blobs` accumulates per graph step and can
  dwarf everything else (5.8 GB here). It is resumable-run state, not history:
  prune it if the database gets heavy.
- **`API_KEY_ENCRYPTION_KEY` must be stable** — changing it orphans stored keys.
- **Stray skill directories** — a directory whose `SKILL.md` declares a
  non-kebab-case id (e.g. `skills/market_wizard/`) is reported and skipped by the
  sync rather than failing the install.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `psycopg ... connection refused :5432/:5433` | Postgres not started → step 1 (`docker compose up -d postgres` / `brew services start postgresql@16` / `sudo systemctl enable --now postgresql-16`) |
| `extension "vector" is not available` / embedding errors | pgvector not installed on the OS → install it per the matching option in step 1 (Docker bundles it; native: `brew install pgvector`, `apt install postgresql-16-pgvector`, `dnf install pgvector_16`) |
| `npm: command not found` / frontend won't start | Node not installed → install via nvm (step 4 → "Node.js — required for the frontend UI"), then `npm install` |
| `neo4j ... could not connect` / auth failed / no labels in Graph Studio | Neo4j not running or wrong credentials → start the container (step 1 → "Neo4j"), check the `NEO4J_*` block in `.env` (Aura: set `NEO4J_ENCRYPTED=true` and use the Aura URI), then `uv run python langgraph/test_neo4j_agent.py unit` |
| Seed step 1 prints manual CREATE ROLE instructions | App user can't connect as superuser → run the two `psql` commands it prints, then re-run `seed_all.py` |
| `column custom_tools.definition does not exist` | Stale schema from an earlier seed run (the `custom_tools` table predates the tools refactor) → drop the DB and re-seed: `sudo -u postgres psql -c "DROP DATABASE IF EXISTS langconfig;"` then re-run `uv run python scripts/seeds/in/seed_all.py` |
| `permission denied to create extension "vector"` | The `langconfig` role lacks superuser (native installs create it with only `CREATEDB`) → `sudo -u postgres psql -c "ALTER ROLE langconfig SUPERUSER;"` then re-run the seed |
| `deep agents: 0` after health check | Run step 7; verify `WORKSPACE_ROOT` was exported |
| `WORKSPACE_BASE/` or `{{...}}` visible in an agent's prompt | Backfill didn't run → `uv run python scripts/seeds/in/backfill_agent_identity.py --workspace-root <root>` |
| Frontend blank on :1421 | `npm install` then `bash start.sh --fe` |
| API key not working | Add it in Settings → Models (DB, encrypted); verify `API_KEY_ENCRYPTION_KEY` is set in `.env` |
