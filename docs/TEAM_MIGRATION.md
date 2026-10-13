# Team migration — code, database, and smoke test

How to bring a new machine (or a teammate's) from `git clone` to a working
install that matches the team's agents, tools, models and skills — **without
touching anything they have already built**.

Companion to [`TEAM_INSTALL.md`](TEAM_INSTALL.md), which covers the same ground
for a zip-package install. Where the two disagree on counts, trust this file:
the numbers there have drifted (it still advertises 44 agents / 28 models /
58 tools / 19 skills).

---

## 0. What travels, and what does not

| layer | how it moves | notes |
|---|---|---|
| **code** | `git clone` / `git pull` | `learning/` (the phase-9 GraphIndex package the chat path imports), `backend/skills/**` and all seed assets are tracked |
| **schema** | `alembic upgrade head` | the installer stamps head on a fresh database; an existing one needs a real upgrade |
| **agents** | `seeds/deep_agents_merge.sql` | **additive**: inserts only names that are absent |
| **tools** | `seeds/custom_tools_merge.sql` + `seed_builtin_tools.py` | **union** on `tool_id`; built-ins are refreshed in place |
| **models** | `seeds/models_seed.csv` + `upsert_model.py --preset deepseek-flash` | the CSV alone has no vision model |
| **skills** | `backend/skills/**` → FS→DB sync | three roots: `builtin/`, `personal/`, and top-level `<id>/` |
| **settings** | `seed_settings.py` (missing namespaces only) | team values; never machine paths |
| **per machine** | `.env`, API keys, `backend/outputs/` | secrets and workspaces are local by design |

**Deliberately NOT migrated:** `chat_sessions`, `conversation_archives`, the
LangGraph checkpoint tables, and uploaded document blobs. Each person keeps their
own history. This is also why a full `pg_dump` is the wrong tool — on one real
install **5.8 GB of a 6 GB database was `checkpoint_blobs`** (resumable graph
state), against ~1 MB of actual team knowledge (56 agents + 68 tools + 29 models
+ 43 skills).

---

## 1. Prerequisites

| need | version | why |
|---|---|---|
| git | any | |
| Docker + compose | recent | Postgres 16 with pgvector (`pgvector/pgvector:pg16`) |
| Python | **3.13** (`requires-python >=3.13`) | backend |
| uv | recent | dependency sync from `uv.lock` |
| Node.js | 20+ (Vite 7) | frontend |
| tesseract | optional | OCR for `read_any_file`; without it the reader says so and falls back to the vision model |
| Ollama | optional | embeddings (`ollama-nomic-embed-text`) — document/RAG indexing is the only thing that needs it |
| Redis | optional | only the LangGraph redis cache backend uses it; compose ships it anyway |

```bash
# Ubuntu
sudo apt update && sudo apt install -y git curl ca-certificates unzip
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER   # re-login after
curl -LsSf https://astral.sh/uv/install.sh | sh
# macOS: brew install git uv node postgresql@16   (or Docker Desktop)
```

## 2. Clone and configure

```bash
git clone git@github.com:sailor723/langconfig.git
cd langconfig
cp env_example .env
```

Then edit `.env`. The required block:

```ini
POSTGRES_HOST=localhost
POSTGRES_PORT=5433          # 5433 with docker-compose, 5432 native
POSTGRES_DB=langconfig
POSTGRES_USER=langconfig
POSTGRES_PASSWORD=langconfig_dev     # change it, and mirror it in docker-compose
ENVIRONMENT=development

# Encrypts provider API keys stored in the database. Generate ONCE per machine
# and keep it: rotating it makes every stored key undecryptable.
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
API_KEY_ENCRYPTION_KEY=

STORAGE_MODE=db             # db = uploads in Postgres (BYTEA); fs = on disk
LANGCONFIG_WORKSPACE_ROOT=backend/outputs
OLLAMA_BASE_URL=http://localhost:11434
```

> Create `.env` **before** starting Postgres: `docker compose` reads
> `POSTGRES_PORT` at compose time to decide the host port mapping.

## 3. Database up

```bash
docker compose up -d postgres
docker ps                      # langconfig-postgres ... 0.0.0.0:5433->5432/tcp
```

## 4. Backend dependencies

```bash
cd backend
uv sync                        # creates backend/.venv from uv.lock
# fallback without uv:
# python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 5. Seed the database — this is the migration

```bash
cd backend
.venv/bin/python scripts/seeds/seed_all.py
```

Idempotent and **additive**. It is safe to re-run, and safe to run on a database
that already has a teammate's work in it. The ten steps:

1. `init_server()` — create the role and database if missing
2. `init_db()` — 50 tables + the pgvector extension
3. `alembic stamp head` — record the migration version (fresh DB; use
   `alembic upgrade head` on an existing one)
4. `seed_settings.py` — default settings documents, **missing namespaces only**
5. `seed_models.py` + `upsert_model.py --preset deepseek-flash` — catalog
6. `seed_search_providers.py` — 6 search backends
7. tools — `custom_tools_dump.sql` (only if the table is empty), then the
   **additive** `custom_tools_merge.sql`, then built-in refresh
   (`seed_builtin_tools.py`, `seed_read_any_file_tool.py`)
8. agents — **additive** `deep_agents_merge.sql`
9. identity backfill — resolves each agent's real workspace and bakes identity
10. skills — FS → DB sync; chinook sample DB (best-effort)

**The guarantee:** agents and tools are united on their identity
(`name` / `tool_id`). A teammate with 5 tools, where 3 match yours, ends with
8 — and their 3 keep **their** version. Nothing is truncated, renamed or
rewritten. The only destructive path is the explicit flag:

```bash
.venv/bin/python scripts/seeds/seed_all.py --replace   # TRUNCATEs agents + tools,
                                                       # and CASCADE takes their chat sessions
```

Optional, for a test run that must not touch real workspaces:

```bash
WORKSPACE_ROOT=/tmp/langconfig-ws .venv/bin/python scripts/seeds/seed_all.py
```

## 6. Provider API keys

Credentials live in the **database**, encrypted with `API_KEY_ENCRYPTION_KEY`
(provider selection reads the `models` table; keys come from the settings
document). Add them per machine — **Settings → API Keys** in the UI.

Do **not** copy `settings_documents` between machines: the `models.api_keys`
document holds ciphertext that only decrypts with the key that wrote it, and the
`workspace` namespace holds an absolute path from the machine it came from.

## 7. Run it

```bash
bash start.sh                  # backend :8765 + frontend :1421, one-shot
# or separately:
cd backend && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765 --workers 1
npm run dev                    # frontend :1421
```

Note: the backend runs **without `--reload`**, so backend code changes need a
restart; frontend changes hot-reload.

## 8. Smoke test

```bash
cd backend
.venv/bin/python scripts/smoke_test.py                 # database + seed + API
.venv/bin/python scripts/smoke_test.py --chat 112       # also one real agent turn
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

Reference run on this install:

```
[1] database        PASS  agents=56, tools=68, models=29, skills=43, settings=8
[2] seed content    PASS  9 checks (vision models: 18, read_any_file: 1 row)
[3] backend API     PASS  4 endpoints HTTP 200
=== 15 passed, 0 failed, 1 skipped ===
```

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
POSTGRES_DB=langconfig_seedtest .venv/bin/python scripts/seeds/verify_additive_seed.py
POSTGRES_DB=langconfig_seedtest .venv/bin/python scripts/seeds/verify_tools_union.py
```

## 9. Shipping later work to the team

**Agents and tools live in Postgres, not in git.** Creating or editing one in the
UI changes nothing in the repository, so the snapshots under
`backend/scripts/seeds/` are the only thing that carries them to a teammate — and
a stale snapshot fails *silently*: their `seed_all.py` just adds nothing new.

One command does the whole "seed out", and tells you whether you were due:

```bash
cd backend
.venv/bin/python scripts/seeds/export_baseline.py           # photograph the DB into the repo
.venv/bin/python scripts/seeds/export_baseline.py --check    # am I due? (exit 1 if yes)
git add scripts/seeds/*.sql && git commit -m "chore(seeds): refresh team baseline"
```

`--check` catches both kinds of drift: a **new** row (counts differ) and an
**edited** row (counts identical, bytes differ) — the second is why it compares
the regenerated file byte-for-byte rather than counting rows.

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
`scripts/seeds/check_tool_overlap.py` reports those candidates on demand, and the
Tool Library is where a user deletes the redundant one.

## 10. Footguns

- **`--replace` is destructive** — truncates agents and tools; the CASCADE also
  removes those agents' chat sessions.
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
