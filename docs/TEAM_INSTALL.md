# LangConfig — Team Installation Guide

> Install LangConfig from the zip package on a fresh machine: PostgreSQL setup,
> uv, unzip, dependency sync, database seed (with your workspace), LLM API keys,
> health check, and startup.

---

## 0. What you receive

`langconfig.zip` (≈12 MB) contains the full source tree minus secrets/build
artifacts (no `.env`, `node_modules`, `.venv`, `data`, `backend/outputs`, git
history). The database seed restores a machine-agnostic baseline: 44 deep
agents, 28 LLM models, 58 tools, 19 skills. **Your workspace paths and API keys
are added locally in the steps below — nothing machine-specific ships in the
zip.**

---

## 1. PostgreSQL — install & setup

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

### Option A — Docker (simplest, recommended for team)

```bash
# from the unzipped folder
docker compose up -d postgres
# container: langconfig-postgres on host port 5433 (→ container 5432)
# health: docker ps   →  "langconfig-postgres  0.0.0.0:5433->5432/tcp"
```

### Option B — Native PostgreSQL 16 (macOS Homebrew)

```bash
brew install postgresql@16
brew services start postgresql@16
# on :5432; create the role + database once (or let seed_all.py do it — it
# auto-creates role/db when the app user can connect as superuser):
psql postgres -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB;"
psql postgres -c "CREATE DATABASE langconfig OWNER langconfig;"
```

### Option C — Native PostgreSQL 16 (Ubuntu / WSL2)

```bash
sudo apt install -y postgresql-16 postgresql-16-pgvector   # pgvector for embeddings
sudo service postgresql start
sudo -u postgres psql -c "CREATE ROLE langconfig LOGIN PASSWORD 'langconfig_dev' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE langconfig OWNER langconfig;"
```

> The role needs `CREATEDB` because `seed_all.py` step 1 creates the DB if
> missing, and step 10 creates the `chinook` sample DB for Graph Studio.

---

## 2. Install uv (Python 3.13 manager)

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

## 3. Unzip the package

```bash
unzip langconfig.zip -d langconfig
cd langconfig
ls          # AGENTS.md  backend/  docker-compose.yml  docs/  package.json  src/  start.sh  scripts/ ...
```

---

## 4. Sync Python dependencies (`uv sync`)

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

---

## 5. Configure `.env` BEFORE seeding — split by who owns the value

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
API_KEY_ENCRYPTION_KEY=replace-me-with-`openssl-rand-hex-32`-output
ENVIRONMENT=development
TEST_DATABASE_URL=postgresql+asyncpg://langconfig:langconfig_dev@localhost:5433/langconfig_test
SQL_POSTGRES_DB=chinook
GOOGLE_REDIRECT_URI=http://localhost:8765/api/auth/google/callback
OLLAMA_BASE_URL=http://localhost:11434
SQL_ECHO=false
RATE_LIMIT_CLEANUP_INTERVAL=300

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

The workspace the team actually wants to know about is the **per-agent output
folder** (where agents write files): `<some-root>/agents/agent_{id}/`. The seed
seeds 44 agents with no `workspace_path` set, so on first start every agent
defaults to `<repo>/backend/outputs/agents/agent_{id}/` (where `<repo>` is the
LangConfig repo root). The team can change this in three ways:

1. **Per-agent `workspace_path` in the DB** (the canonical path). Set
   `deep_agent_templates.workspace_path` to an absolute path (or a path
   relative to the workspace settings document's `langconfig_workspace_root`).
   Editable from the Settings panel for each agent, or in bulk via the
   Settings → Runtime → `langconfig_workspace_root` (set the global base, then
   each agent's resolved workspace = base + agent_vault_key).

2. **Bulk-update via the backfill script** (`scripts/backfill_agent_identity.py`):
   sets each agent's resolved workspace under the given root with the correct
   `agent_{id}/` segment. This is the only way to change the resolved
   filesystem layout for every agent at once.

3. **`.env` value `LANGCONFIG_WORKSPACE_ROOT`** is **NOT** the per-agent root.
   It's read by `services/agents_md_service.py` to locate the project-level
   `AGENTS.md` directory (under `<root>/{project_id}/`). It is *not*
   used by the per-agent workspace resolution, the seed, or the backfill.

**In short**: the answer to "do I set it in `.env` with seed_all.py?" is **no** —
the seed always uses the legacy default unless you explicitly set the per-agent
`workspace_path` column. The first-time setup is "do nothing special; let the
legacy defaults apply; the team can override at runtime via the Settings panel".

---
---

## 6. Apply LLM API keys (in the DB, not in `.env`)

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

## 7. Run the database seed

From `backend/`:

```bash
cd backend
WORKSPACE_ROOT=/Users/<you>/langconfig/backend/outputs \
  uv run python scripts/seeds/seed_all.py
```

What it does (10 steps, all idempotent):

| Step | Action |
|---|---|
| 1 | create Postgres role + database if missing |
| 2 | create all tables + pgvector extension |
| 3 | alembic stamp head |
| 4–6 | seed settings documents, 28 models, 6 search providers |
| 7 | restore 58 tools |
| 8 | restore 44 deep agents (machine-agnostic dump) |
| **8.5** | **identity backfill** — bakes each agent's real id + `<WORKSPACE_ROOT>/agents/agent_{id}` + AGENTS.md/CLAUDE.md into `system_prompt` + `agent_docs` |
| 9 | sync 19 skills from `backend/skills/` |
| 10 | create `chinook` sample DB (best-effort) |

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
> `uv run python scripts/backfill_agent_identity.py --workspace-root <new>`

---

## 8. Pre-start health check

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

## 9. Start the full stack

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

## Troubleshooting

| Symptom | Fix |
|---|---|
| `psycopg ... connection refused :5432/:5433` | Postgres not started → step 1 (`docker compose up -d postgres` / `brew services start postgresql@16`) |
| Seed step 1 prints manual CREATE ROLE instructions | App user can't connect as superuser → run the two `psql` commands it prints, then re-run `seed_all.py` |
| `deep agents: 0` after health check | Run step 7; verify `WORKSPACE_ROOT` was exported |
| `WORKSPACE_BASE/` or `{{...}}` visible in an agent's prompt | Backfill didn't run → `uv run python scripts/backfill_agent_identity.py --workspace-root <root>` |
| Frontend blank on :1421 | `npm install` then `bash start.sh --fe` |
| API key not working | Add it in Settings → Models (DB, encrypted); verify `API_KEY_ENCRYPTION_KEY` is set in `.env` |
