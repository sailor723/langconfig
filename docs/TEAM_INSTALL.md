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

## 5. Configure `.env` (including workspace) BEFORE seeding

Create the root `.env` (single source of truth — the backend, seeds, docker and
frontend all read it). Minimal template:

```bash
# backend/../.env  (repo root)
ENVIRONMENT=development

# ── Secrets at rest (generate once:  openssl rand -hex 32) ──
API_KEY_ENCRYPTION_KEY=REPLACE_WITH_64_HEX

# ── PostgreSQL (match step 1) ──
POSTGRES_HOST=localhost
POSTGRES_PORT=5433          # docker; use 5432 for native
POSTGRES_DB=langconfig
POSTGRES_USER=langconfig
POSTGRES_PASSWORD=langconfig_dev
```

### The workspace parameter — how to pass it to seeds

Every agent needs a real workspace folder on **this** machine (their identity
block + AGENTS.md/CLAUDE.md get re-baked with it at seed time). Two ways:

**A) Environment variable (recommended for team):**
```bash
export WORKSPACE_ROOT=/Users/<you>/langconfig/backend/outputs
```
Agents resolve to `<WORKSPACE_ROOT>/agents/agent_{id}/` (custom `workspace_path`
agents use their own folder under the root).

**B) Or let it default** — with no override, the workspace manager resolves to
`<repo>/backend/outputs/agents/agent_{id}/` automatically.

---

## 6. Apply LLM API keys

API keys are resolved at runtime in this order (`config.py::get_api_key_from_db`):

1. **`.env` file** (pydantic-settings) — **canonical source of truth**
2. **PostgreSQL** — the `models` settings document's `api_keys` field (set via
   the Settings UI, encrypted at rest with `API_KEY_ENCRYPTION_KEY`)

So you can add keys **either** way; if both are set, `.env` wins. For a team
install, the Settings UI (DB) is the most convenient — no file editing:

1. **First-run wizard in the UI** — open `http://localhost:1421` after startup,
   the Setup wizard prompts for API key + workspace.
2. **Settings → Models** after boot — add provider keys (OpenAI / Anthropic /
   DeepSeek / Google / MiniMax / Tavily …).

> Which key(s) you need depends on the models your agents use. The seeded agents
> default to Anthropic (`claude-sonnet-4-5`) / DeepSeek models — at minimum add
> the provider key matching your default model, e.g. `ANTHROPIC_API_KEY` or
> `DEEPSEEK_API_KEY` (in `.env` **or** Settings → Models).

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
