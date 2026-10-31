# LangConfig — Backend

FastAPI service that turns the UI's configuration into running LangChain agents and
LangGraph workflows. Python **3.13**, PostgreSQL **16 + pgvector**, LangChain v1,
LangGraph, `deepagents` 0.7.1.

The project-wide overview lives in [`../README.md`](../README.md); the full design is in
[`../docs/system-architecture.md`](../docs/system-architecture.md).

## Run

```bash
cd backend

.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8765
# or, for the whole stack (Postgres + API + UI):
bash ../start.sh
```

Serves on **:8765**. Swagger UI at `/docs`, ReDoc at `/redoc`, OpenAPI at `/openapi.json`.
Startup fails loudly if PostgreSQL is unreachable — nothing degrades silently there.

Environment comes from the **root** `.env` (loaded by `config.py` and `db/database.py`).
`db.db_url.compose_db_url()` builds `DATABASE_URL` from the `POSTGRES_*` block, so the app,
`docker-compose.yml` and the seed scripts always agree on host/port/database.

## Database

```bash
docker compose -f ../docker-compose.yml up -d postgres   # pgvector/pg16, host port = $POSTGRES_PORT
.venv/bin/python -m alembic upgrade head                 # migrations
.venv/bin/python scripts/seeds/in/seed_all.py               # idempotent bootstrap + data load
```

- **Schema** — 48 tables. `async_init_db()` registers every `models.*` module, enables
  `vector` + `uuid-ossp`, then `create_all`. Because `create_all` never `ALTER`s an existing
  table, startup also adds any column the models declare but the database lacks
  (`_add_missing_model_columns`) — idempotent, and it only ever adds.
- **Migrations** — 33 revisions, head `031_chat_session_title`. Fresh installs use
  `create_all` + `alembic stamp head` rather than replaying `001_initial_schema`, which is
  not replayable on an empty database.
- **Seed** — `scripts/seeds/in/seed_all.py` is additive and safe to re-run: it inserts only
  what is missing and never rewrites rows somebody edited. `--replace` is the opt-in
  force-reload for agents/tools.

## How it is organised

| Path | What lives there |
|---|---|
| `main.py` | app factory, lifespan (startup wiring: DB, settings, checkpointing, MCP, skills sync, task queue, scheduler, file watchers), **45 routers** |
| `api/` | REST + SSE routers — thin: parse, delegate, stream |
| `core/agents/factory/` | `AgentFactory.create_agent` → LangChain `create_agent` |
| `services/deepagent_factory/` | `DeepAgentFactory.create_deep_agent` → `deepagents` |
| `core/workflows/executor/` | LangGraph execution engine (mixin package) |
| `core/workflows/checkpointing/` | Postgres checkpointer, HITL, thread cleanup |
| `core/settings/` | DSH-style settings documents (schema, store, encrypt, seed) |
| `core/tools/` | tool factory + native tool implementations |
| `core/skills/` | skill registry, FS↔DB sync, matcher |
| `services/` | 48 support modules + 4 sub-packages (storage, workspace, schedulers, MCP, dashboards) |
| `models/` | SQLAlchemy ORM models |
| `db/` | engines, sessions, URL composition, schema-init parity helpers |
| `scripts/seeds/` | seed data + dumps (the bootstrap source of truth) |
| `skills/` | `builtin/` and `personal/` `SKILL.md` trees (git-tracked mirror of the DB) |
| `tests/` | pytest suite |

## Tests

```bash
.venv/bin/python -m pytest \
  --ignore=tests/test_neo4j_document_enrichment.py \
  --ignore=tests/test_pageindex_full_content_loader.py
```

**591 passed, 3 failed, 18 skipped** (≈21 s). The two ignored modules are stale — they import
symbols that were removed (see `../REFACTORING.md`) — and they break bare `pytest` collection;
deleting them is the fix, until then the `--ignore` flags are required.

The 3 failures are pre-existing and unrelated to these ignores: `test_graphindex_search_via_neo4j.py`
and `test_neo4j_autosync.py` reference removed GraphIndex APIs, and
`test_storage.py::test_upload_and_doc_chat_are_the_same_folder` is a local in-progress edit
(it unpacks `_scan_folder_sync()` as a 2-tuple, but it returns a list).

## Configuration

Settings are **DB-first**. The `settings_documents` table holds one row per namespace
(`general`, `models`, `agents`, `knowledge`, `rag`, `storage`, `workspace`, `runtime`,
`onboarding`, `search`), each validated against a pydantic schema, revision-guarded, and
Fernet-encrypted for `role="secret"` fields. The Settings UI is the write path.

`.env` carries **infrastructure only** — database, storage mode, workspace roots, rate
limits, tracing. Provider credentials belong in the database; a key found in `.env` is
ignored and reported once at boot (`config.py: warn_on_env_credentials`).

## Windows / WSL notes

`psycopg` requires a `SelectorEventLoop`, so `main.py` sets
`WindowsSelectorEventLoopPolicy` on win32 before anything else imports asyncio. Do not
move that guard below the FastAPI imports.
