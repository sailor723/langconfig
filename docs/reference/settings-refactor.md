# Settings Refactor — DSH-style namespaced settings on Postgres

Status: **design (approved 2026-08-15)** — see REFACTORING.md for the broader
backend cleanup this is part of.

## 1. Goal

Rebuild LangConfig settings after the DeepSeek Harness settings model
(`packages/settings/settings`, `settings-file`, `client/ui-settings*`), adapted
to our stack:

- **Everything configurable lives in PostgreSQL** — the Settings UI is the
  editor for all of it.
- **Namespaces + JSON schemas** — each domain (`models`, `general`,
  `workspace`, …) owns a namespace with a pydantic schema (our schemastery
  analog). The schema defines shape, renders the UI, validates writes.
- **Base layer shrinks to bootstrap-only** — `.env` keeps exactly what cannot
  live in the DB: `DATABASE_URL` and `API_KEY_ENCRYPTION_KEY` (optional
  `ENVIRONMENT`). Everything else migrates into DB documents.
- **Generic wire API** — `describe`/`mutate` replace the 26 bespoke endpoints
  in `backend/api/system/settings.py` (1229 L).

Confirmed decisions: write seeded defaults **into** the DB documents; idempotent
**boot auto-seed**; align `scripts/setup.py` with `scripts/seeds/in/seed_all.py`;
fold in the uncommitted NULL-defaults work (`backend/models/settings.py` +
migration `027`).

## 2. End-state architecture

```
resolved value =  pydantic schema defaults (code, last resort)
              →  DB user document (namespace JSONB + revision)
              →  consumed by AgentFactory._create_llm, agent_utils,
                 workflow executor, selector, sql_agent, …

bootstrap only (env / minimal .env):
  DATABASE_URL · API_KEY_ENCRYPTION_KEY · ENVIRONMENT(optional)
```

- `.env` is **read-only at runtime**. First-boot seeding (below) copies today's
  `.env` values into the DB once; runtime edits go through `mutate` → DB.
- No code path writes `.env` (verified: none exists today; this design keeps it
  that way).
- In production the file can disappear entirely — the three bootstrap vars come
  from real environment variables (docker-compose / systemd / Tauri shell).

### Why two values cannot move into the DB

| Value | Why it must stay outside |
|---|---|
| `DATABASE_URL` | You cannot read settings *from* the DB before you can connect *to* it. |
| `API_KEY_ENCRYPTION_KEY` | Fernet seed that encrypts every stored secret (`services/encryption.py`). If it lived in the DB it would sit beside the ciphertext it decrypts — and you'd need the key to read the key. Phase 4 (`d954134`) fixed exactly the class of bug this would reintroduce. |

## 3. Namespaces (v1)

| ns | Schema (pydantic) | Fields (user-layer document) |
|----|-------------------|------------------------------|
| `general` | `GeneralSettings` | app_name, language, auto_save, auto_save_interval, confirm_before_delete, show_notifications, check_updates, telemetry, log_level, theme |
| `models` | `ModelsSettings` | apiKeys (`role='secret'` per provider — openai/anthropic/deepseek/…), default_model, default_temperature, max_tokens, primary_model, fallback_models, top_p, routing_strategy, daily/monthly_token_limit, alert_threshold, local provider/base_url/model/api_key |
| `workspace` | `WorkspaceSettings` | workspace_path, allow_read/write, require_approval, auto_detect_git, backup_before_edit, base_dir |
| `storage` | `StorageSettings` | mode (local/db), base_dir, documents_base_dir |
| `rag` | `RagSettings` | embedding_model, chunk_size, chunk_overlap |
| `search` | `SearchSettings` | provider keys (tavily/serper/…, `role='secret'`) |
| `onboarding` | `OnboardingSettings` | setup_complete, api_key_set, workspace_set |

Seed-time defaults live in `core/settings/defaults.py::get_defaults()` (hardcoded
after Phase 5b — no `.env` values are read for content/settings). A fresh
install has no `env_example`: `scripts/setup.py` **generates** the minimal
`.env` (Postgres bootstrap + a randomly generated Fernet encryption key), and
the first boot seeds the documents from `get_defaults()`. API keys are entered
in the first-run wizard / Settings → Models (stored encrypted in the DB); the
only `.env` values still read are the Postgres connection, the encryption key,
and the optional infra overrides (LangSmith/OAuth/webhooks/tests/build).

## 4. DB shape

New table (alembic `028_create_settings_documents`):

```sql
CREATE TABLE settings_documents (
    ns         VARCHAR(64) PRIMARY KEY,          -- 'models', 'general', …
    document   JSONB NOT NULL DEFAULT '{}',      -- user layer section
    revision   INTEGER NOT NULL DEFAULT 0,       -- monotonic per namespace
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- The legacy single-row `settings` table (id=1) **stays** as a shim: old
  endpoints read through it until the frontend migrates; then it is dropped in
  a later migration. `027_clear_settings_model_params` is kept and precedes
  `028` (legacy model columns NULLed, then documents backfilled).
- `028` also **backfills** `settings_documents` from the current `settings` row
  + `.env` values for existing installs (one-time).

## 5. Resolution engine — `backend/core/settings/`

| Module | Contents |
|--------|----------|
| `registry.py` | `register(ns, schema, validate?)`, `namespaces()`, `get(ns)` — DSH `SettingsRegisterOptions` analog |
| `schemas.py` | the v1 pydantic models (moved from `api/system/settings.py`); `model_json_schema()` per ns |
| `resolve.py` | `resolve(ns) -> {value, base?, user, revision, writable}` — user document merged over schema defaults; secret fields redacted |
| `store.py` | `get_document(ns)`, `mutate(ns, ops, expected_revision) -> (document, revision)`, revision bump + optimistic-conflict detection |
| `secrets.py` | schema-declared `role='secret'` redaction at the wire (DSH `redact.ts` analog) + Fernet encrypt/decrypt at rest |
| `defaults.py` | `get_defaults()` — seed documents **derived from the current `.env`** via `config.Settings`, with hardcoded fallbacks for keys removed when `.env` shrinks (Phase 5) |

Resolution rule: **DB document wins; pydantic defaults fill gaps.** There is no
`.env` runtime layer anymore — `.env` only fed the seed/backfill.

Consumers migrate from ad-hoc column access to typed accessors:
`get_settings_value("models", ModelsSettings)` (or `settings_store.models`).

## 6. Wire API — `backend/api/system/settings.py` slims down

```
GET  /api/settings/describe       → {namespaces: [{ns, schema, value, user,
                                     revision, writable, secrets[]}], writable}
POST /api/settings/mutate         → {ns, ops: [{op:'set'|'unset', path, value?}],
                                     expectedRevision}
                                    200 → {ns, value(redacted), revision, secrets[]}
                                    409 on stale · 404 unknown ns · 422 schema-invalid
```

(Note: `describe` lives at `/api/settings/describe`, not `/api/settings`, because
the legacy `GET /api/settings/` route owns the bare path until it is deleted.)

- Secret fields are stripped from `value`/`user` at the wire and enumerated in
  `secrets[]` (`{path, set}`) — the UI renders write-only inputs with
  set/missing dots (DSH `ProviderEditor` behavior).
- The 26 existing endpoints stay **untouched and fully functional** during the
  frontend migration (Phase 4); they are deleted once `SettingsPage.tsx` +
  `SetupWizard.tsx` are on `describe`/`mutate` (Phase 5).
- Fixes the known inconsistencies found during study:
  - `SettingsResponse.default_model: str` etc. would 500 on NULL → gone with
    the bespoke `GET /api/settings/` shape.
  - `reset_settings` re-hardcoding `gpt-4o`/`0.7`/`4096` → reset becomes
    `mutate(ns, [{op:'unset', path:[...]}] * all)` → falls back to seed defaults.
  - `ModelDefaultsSettings` legacy fallback defaults → schema defaults only.

## 7. Seed & bootstrap (team installs)

- **New `backend/scripts/seeds/in/seed_settings.py`** — idempotent: if
  `settings_documents` is empty, insert the default documents from
  `core/settings/defaults.py` (never overwrites existing rows; same
  empty/under-populated pattern as `deep_agents_dump.sql`).
- **`seed_all.py`** gains a step right after `init_db` + stamp:
  `uv run python scripts/seeds/in/seed_all.py` → fully working install.
- **Boot auto-seed** — `main.py` lifespan calls idempotent
  `ensure_settings_seeded()` (no-op when documents exist), same pattern as the
  existing boot-time skills FS→DB sync.
- **`scripts/setup.py` aligned** — its `init_database()` path delegates to
  `seed_all.py` (fixes the stale `006_skills_system` stamp and the missing
  seeds); `setup_env_file()` now **generates** the minimal `.env` (Postgres
  bootstrap + randomly generated `API_KEY_ENCRYPTION_KEY`) — `env_example`
  was deleted.
- **Existing installs** — `028` backfill covers them; no manual step.

## 7.5 Team install — zip distribution (no git)

Canonical install story for team members who do not use git:

1. **Send `.zip`** — source bundle built by `scripts/make_team_zip.sh` (new):
   working tree + `docker-compose.yml` + `backend/scripts/seeds/*`. Excludes
   `.env`, `node_modules/`, `.venv`, `dist/`, `data/`, `backend/outputs/`,
   `.git/`. Secrets never ship.
2. **Unzip + one-time setup** — `python backend/scripts/setup.py`: **generates**
   `.env` (Postgres bootstrap + encryption key), installs deps, starts
   Postgres (`docker compose up -d postgres`), then delegates the DB step to
   `seed_all.py`. Requires Python 3.13 + Node + Docker (internet for
   `npm install` / `uv sync`) — **no git**.
3. **Seed all = initial DB** — `seed_all.py` (idempotent): role+DB if missing →
   50 tables + pgvector → stamp → models(28) → search providers → tools(53) →
   deep agents(42) → skills → **settings documents (new step)** → chinook
   (best-effort). Fresh install works with zero `.env` beyond bootstrap.
4. **First browser open** — boot runs `async_init_db()` +
   `ensure_settings_seeded()` (no-op when documents exist) →
   `setup_status.needs_setup=true` → SetupWizard asks for API key + workspace
   → `mutate` into `models`/`workspace`/`onboarding` (key encrypted at rest
   with `API_KEY_ENCRYPTION_KEY`). Only runtime input at first boot — DSH-like.
5. **Start work / more settings** — `bash start.sh`; everything else editable
   in the Settings modal (search providers, storage mode, RAG, token limits,
   local models…), all persisted to Postgres documents.

Notes: `.env` is `POSTGRES_*` + `API_KEY_ENCRYPTION_KEY` (+ optional `ENVIRONMENT`
and infra overrides). Without the key, `services/encryption.py` uses the dev
fallback with a warning (production must set it). A zero-toolchain bundle
(shipping `node_modules` + venv, ~2.3 GB) is explicitly rejected — the
`setup.py` path is the standard. The Aug-13 `langconfig.zip` is stale and will
be replaced by the packaging script output.

**Verification timing:** this flow is the *post-refactor* target state. It is
only meaningful to test end-to-end after Phase 1–5 land (`.env` shrunk,
`config.py` slimmed, `settings.py` namespaced). Until then, testing it would
exercise the old `.env`/`config.py`/`settings.py` world. The full install test
is a Phase-5 exit criterion, not a Phase-1 one.

## 8. Frontend (Phase 4 — done)

- `src/pages/SettingsPage.tsx` — **General, Models, Workspace sections** now read
  from `GET /api/settings/describe` and write via `POST /api/settings/mutate`
  (optimistic local updates; re-read on 409/error). Provider rows derive from
  the redacted secret positions (`secrets[]` → set/missing dots); key values
  never cross the wire. `Search` + `Storage` sections stay on their legacy
  endpoints (search_providers table / runtime storage-mode switch) until
  Phase 5.
- `src/components/layout2/SetupWizard.tsx` — provider list from `describe`
  (models secrets), API key saved via `mutate` into `models.api_keys`,
  workspace path via `mutate` into `workspace.workspace_path`. Keeps legacy
  `setup-status`, `completeSetup`, `validateWorkspacePath`, `testApiKey`.
- `src/lib/api/settings.ts` — added `describeSettings()` + `mutateSettings()`
  (legacy methods stay until the endpoints are deleted).
- **Legacy write-through mirror** (`api/system/settings_documents.py`):
  every `mutate` on `models` mirrors `api_keys` → `settings.api_keys`
  (encrypted) and on `workspace` mirrors fields → `settings.workspace_*`, so
  the running app (LLM factory via `config.get_api_key_from_db`,
  `WorkspaceManager` via `settings.workspace_path`) keeps working unchanged.
  Removed in Phase 5 when consumers migrate to `core.settings`.

## 9. Implementation phases

1. **Engine** — `backend/core/settings/` (registry, schemas, resolve, store,
   secrets, defaults) + unit tests. ✅
2. **Migration + seed** — alembic `028_create_settings_documents` (create +
   backfill); `seed_settings.py`; `seed_all.py` step; `main.py` boot
   `ensure_settings_seeded()`; `setup.py` alignment. ✅
3. **Wire API** — `describe`/`mutate` endpoints; legacy endpoints kept working
   (initially with a write-through mirror). ✅
4. **Frontend** — `SettingsPage.tsx` + `SetupWizard.tsx` on the new API. ✅
5. **Cleanup (Phase 5 — done)** — legacy settings-document endpoints deleted;
   legacy write-through mirror removed; backend consumers migrated to the
   engine (`config` keys, `WorkspaceManager`, `file_storage`, boot storage-mode);
   `api/system/settings.py` slimmed 1229 → ~560 lines (kept: model registry,
   embedding-models, key test, setup status/complete, storage-mode runtime
   switch, workspace-path validate, guardrails, directory browser);
   `src/lib/api/settings.ts` pruned to used methods; team zip script
   (`scripts/make_team_zip.sh`, 12 MB bundle).
6. **Phase 5b — `.env`/`config.py` shrink (done)** — the ~32 `config.Settings`
   consumers now read through `core/settings/runtime.py` (`runtime_get` /
   `local_llm_config`), resolving from the settings documents with
   seed-default fallbacks so behavior is identical pre/post migration. Deleted
   from `config.py`: `default_model`, `default_temperature`,
   `max_tokens`, `fallback_models`, `top_p`, `default_embedding_model`,
   `local_llm_*`, `storage_base_dir`, `workspace_base_dir`,
   `documents_base_dir`, `chunk_size`, `chunk_overlap`, `default_llm_provider`.
    `env_example` was **deleted** — `setup.py` generates the minimal `.env`
    (`POSTGRES_*` + `API_KEY_ENCRYPTION_KEY`); API keys are wizard-only.
    Optional infra overrides remain (LangSmith/OAuth/webhooks/tests/build/
    pool/logging/rate-limit/analysis/execution-history/storage-mode). The
    user's original file is preserved at `.env.full.bak`.
## 10. Tradeoffs (accepted)

| Pro | Con |
|-----|-----|
| One runtime source of truth; UI edits everything | Config leaves git; infra review moves to seeds/migrations |
| Multi-instance consistent | Fresh install needs the seed step (auto-run on boot covers it) |
| Secrets stay encrypted at rest; key external | Three bootstrap vars still need an env source |
| Matches DSH layering closer than today | Base/user distinction is blurred (defaults live in DB documents, not a separate base layer) |
