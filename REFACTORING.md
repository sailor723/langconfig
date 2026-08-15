# Refactoring Status

Tracks the multi-phase cleanup of the LangConfig backend. Goal: eliminate
god-modules, delete dead code, and make the core engine maintainable without
changing the public API.

**Status: Phases 0–4 complete** (committed on `codex-chat-ui-refactor`).

| Phase | Work | Commits | Status |
|-------|------|---------|--------|
| 0 — Safety fixes | Latent runtime crash repair | `ae904f3` | ✅ done |
| 1 — Delete dead code | ~27k lines removed | `201fcb9` | ✅ done |
| 2 — Shared extraction/dedup | Doc-type maps, api-client split, shared editor components | `5c2f474`, `947950d` | ✅ done |
| 3a — Route splits | `api/chat`, `api/workflows`, `api/workspace` → sub-router packages | `cd17d25`, `37ee086`, `f79472a`, `8cf2cbf` | ✅ done |
| 3b — Engine splits | `core/workflows/executor.py`, `events/emitter.py`, `core/tools/factory.py`, `services/deepagent_factory.py` → mixin packages | `1410bc0`, `06abe27`, `82de6e2`, `f5402dc` | ✅ done |
| 3c — Large god-modules | `api/knowledge/rag.py`, `core/agents/factory.py` → route/mixin packages | `d94bf4e`, `7fc2078` | ✅ done |
| Test cleanup | Fixed 4 pytest collection errors from stale tests | `0ff16d1` | ✅ done |
| 4 — Security & correctness pass | Encryption key source, python_function `exec` sandbox, path-traversal/SSRF guards, safe expression eval, checkpointing defaults, DB-driven model registry | `d954134`, `0b23ce0`, `62d88c0`, `5138ff2` | ✅ done |
| 5 — Settings refactor (DSH-style) | `core/settings/` engine + describe/mutate wire API + legacy endpoint cleanup + `.env`/`config.py` shrink + team zip script — see `docs/settings-refactor.md` | *(in progress on branch)* | ✅ done (engine/API/frontend/cleanup + 5b `.env` shrink) |

---

## Phase 4 — Security & correctness pass (uncommitted)

Fixes from the architecture review (each ships with regression tests in
`backend/tests/`; suite went from 200 → ~313 passing with zero new failures):

| Area | Fix |
|---|---|
| Secrets at rest | `services/encryption.py` now reads the documented `API_KEY_ENCRYPTION_KEY` (was the never-set `APP_ENCRYPTION_KEY` → public default key used); refuses the dev fallback in production; `decrypt()` raises on key-rotation mismatch instead of returning ciphertext |
| `python_function` tools | Trust boundary in `core/tools/factory/builders.py`: built-in (git-reviewed) rows keep full exec power; user/agent/bundle tools get AST validation + restricted namespace (no `__import__`/`open`/`eval`, no `os`/`sys`/`pathlib`/`io`/`subprocess`, runtime import gate) |
| Path traversal | `skill_review.py` `csv_stem` sanitized + resolved-path containment; `WorkspaceManager` prefix checks → `Path.is_relative_to` (was `task_1`⊂`task_10`); `FileStorage` hierarchy segments validated |
| SSRF | docx-export image fetch SSRF-guarded + moved off the event loop |
| `eval()` sandbox escapes | new `core/utils/safe_eval.py` (AST-validated; dunder/call allowlists) used by workflow CONDITIONAL/LOOP nodes and emitted by the codegen (with `repr()` escaping) |
| DeepAgent fallback | `assembly.py` only falls back to a regular agent on `ImportError`; other build failures surface with full traceback |
| Guardrails / HITL | removed the always-TypeError `guardrails=` pass-through (deepagents 0.7.1 has no such param); fixed the `_model_str` NameError (harness-profile key now derived from the resolved model) |
| Schema init | `async_init_db()` now registers all ORM models + the `vector` extension, matching sync `init_db()` (was missing 3 tables) |
| Tool scoping | `tool_loader.load_custom` filters by `project_id` (global/same-project/builtin/public only) |
| Specialist agents | `state_modifier=` → v1 `system_prompt` (sql/json agents); `langchain_experimental` import made lazy (pandas agent) |
| Workflow checkpointing | enabled by default in the executor; `interrupt_before` derived from `APPROVAL_NODE`s (real HITL pauses) |
| Model registry | `core/models/registry.py` augments the hardcoded fallback with rows from the `models` table (DB is source of truth, §16.1) |
| Duplicate middleware | assembly drops its instrumented FilesystemMiddleware when a disk backend is active (the SDK injects its own) |
| Checkpoint utils | `checkpointing/utils.py` rewritten on the `AsyncPostgresSaver` API — the old SQL queried non-existent columns (`checkpoint_namespace`, `created_at`) on the sync engine; also added the module-level `delete_thread_checkpoints` that `api/chat/session.py` imports |
| SQL agent dialect | `langgraph/sql_agent.py` generate-query prompt says `postgresql` (was `sqlite`) |

**Known remaining items** (from the review, not yet fixed): `api/chat/skill_review` companions
have no dedicated tests; frontend raw-fetch consolidation (~20 files); the 
`checkpointing` full-table scans (`get_checkpoint_count` etc.) are O(N) over the whole
`checkpoints` table and could be pushed into SQL later.

---

## Phase 3a — Route Splits

Split each god-module route file into a package of sub-routers. The parent
package `__init__` is the sole aggregator (`include_router`), and PEP 562
`__getattr__` lazily re-exports symbols so import order cannot silently drop
routes.

- `api/chat/routes.py` → `api/chat/` (`messages.py`, `session.py`, `context.py`,
  `documents.py`, `skill_review.py`, `schemas.py`, `shared.py`)
- `api/workflows/routes.py` → `api/workflows/` (`crud.py`, `execution.py`,
  `checkpoints.py`, `executions.py`, `exports.py`, `versions.py`, `schemas.py`)
- `api/workspace/routes.py` → `api/workspace/` (`files_routes.py`, `tree_routes.py`,
  `task_files.py`, `schemas.py`)

## Phase 3b — Engine Splits

Split the four core-engine god-modules into mixin packages. Public API is
unchanged: the concrete class lives in the package `__init__`, inherits all
mixins, and module-level symbols are re-exported — no importer changes needed.

### `core/workflows/executor.py` (3367 L) → `core/workflows/executor/`

| Module | Contents |
|--------|----------|
| `shared.py` | `INTERRUPT_AVAILABLE`, `pick_last` reducer, `SimpleWorkflowState` TypedDict, `logger` |
| `execution.py` | `_WorkflowExecutionMixin` — `execute_workflow`, `_validate_and_init_tools` |
| `builder.py` | `_WorkflowBuilderMixin` — `_build_graph_from_workflow` |
| `nodes.py` | `_WorkflowNodesMixin` — node executor creation (`_create_node_executor`, `_create_control_node_executor`, `_create_tool_node_executor`, `_create_llm_node_executor`) |
| `__init__.py` | `class SimpleWorkflowExecutor(_WorkflowExecutionMixin, _WorkflowBuilderMixin, _WorkflowNodesMixin)` + module tail (`_executor`, `get_executor()`, `execute_workflow_sync()`) |

### `core/workflows/events/emitter.py` (1573 L) → `core/workflows/events/emitter/`

| Module | Contents |
|--------|----------|
| `shared.py` | `logger` |
| `callbacks.py` | `_EventCallbacksMixin` — 15 `on_*` LangChain callback methods |
| `internal.py` | `_EventHandlerMixin` — `_emit_event`, sanitization, `_persist_event_to_database`, `flush_pending_persists`, artifact collection |
| `__init__.py` | `class ExecutionEventCallbackHandler(_EventCallbacksMixin, _EventHandlerMixin, AsyncCallbackHandler)` + `create_execution_callback_handler()` |

**⚠️ MRO trap (fixed):** mixins MUST come before `AsyncCallbackHandler` in the
base list. With the base first, 9 of 15 callback methods resolve to langchain's
no-op stubs — silent event loss. A NOTE comment documents this.

### `core/tools/factory.py` (2185 L) → `core/tools/factory/`

| Module | Contents |
|--------|----------|
| `shared.py` | `logger`, `_artifact_lock`, `_pending_artifacts`, `get_pending_artifacts()`, `store_artifact()` |
| `models.py` | `ToolTypes`, `ValidationResult`, `LangChainRequirements` |
| `base.py` | `_ToolFactoryBaseMixin` — `create_tool`, `validate_tool_config`, `get_langchain_requirements`, `_validate_url_ssrf` |
| `builders.py` | `_ToolBuildersMixin` — 16 builder methods (API, notification, image/video, database, data-transform, python-function) |
| `__init__.py` | `class ToolFactory(_ToolFactoryBaseMixin, _ToolBuildersMixin)` + `_schema_cache` + `_bind_runtime()` calls |

### `services/deepagent_factory.py` (912 L) → `services/deepagent_factory/`

| Module | Contents |
|--------|----------|
| `shared.py` | `logger` |
| `preflight.py` | `_DeepAgentPreflightMixin` — `_validate_deep_agent_config`, `_run_skill_router` |
| `assembly.py` | `_DeepAgentAssemblyMixin` — `create_deep_agent` (417 L) |
| `support.py` | `_DeepAgentSupportMixin` — `_load_base_tools`, `_prepare_subagents`, `_load_and_compile_workflow`, `_setup_callbacks`, `_fallback_to_regular_agent` |
| `__init__.py` | `class DeepAgentFactory(_DeepAgentPreflightMixin, _DeepAgentAssemblyMixin, _DeepAgentSupportMixin)` + `_bind_runtime()` calls |

### Key patterns

- **Mixin-based class splitting** — move a god-class's methods into mixins
  organized by domain; concrete class in package `__init__` inherits all mixins;
  `self.method()` semantics preserved via MRO.
- **`_bind_runtime()` late binding** — required for staticmethod-heavy classes
  whose bodies reference the concrete class bare-name (e.g.
  `ToolFactory._schema_cache`, `DeepAgentFactory._fallback_to_regular_agent`,
  `AgentFactory._create_llm`). Each mixin module exposes `_bind_runtime()`; the
  package `__init__` calls it after the concrete class exists.
- **Circular-import hardening** — sub-modules import only from sibling
  `shared.py`/`models.py` modules, never from the package `__init__`.
- **Lazy imports preserved** — every function-level lazy import inside the moved
  methods stays intact (deepagent, workflow executor, DB sessions, etc.).
- **Logger identity** — `logging.getLogger("core.workflows.executor")` etc. moved
  verbatim into each package's `shared.py`.

## Phase 3c — Large god-modules

### `api/knowledge/rag.py` (1758 L) → `api/knowledge/rag/`

Route-file pattern: the package `__init__` owns the single `/api/rag` prefix
and includes prefix-less sub-routers (prefix does not stack, same as the
original `main.py` include).

| Module | Contents |
|--------|----------|
| `shared.py` | `logger` |
| `schemas.py` | 10 pydantic models (upload/search/document/content/history responses) |
| `helpers.py` | `SUPPORTED_GRAPHINDEX_EXTS`, `_is_graphindexable`, `_queue_graphindex_ingest`, `index_document_background`, `_extract_text_for_viewer` |
| `uploads.py` | `upload_document`, bulk upload + folder ingest |
| `documents.py` | list/get/download/content/delete |
| `search.py` | `search_documents`, `index_document`, `get_search_history` |
| `__init__.py` | `router = APIRouter(prefix="/api/rag")` + re-exports in `__all__` |

Verified: all 27 moved nodes byte-identical; all 11 routes present under
`/api/rag`. Removed the orphaned dead tail in `get_search_history`
(`2c2bb5e` remnant after `return history`).

**⚠️ AnnAssign trap (fixed):** the AST-slicing script originally skipped
`SUPPORTED_GRAPHINDEX_EXTS` because module-level annotated assignments are
`ast.AnnAssign`, not `ast.Assign` — it broke server boot
(`ImportError: cannot import name 'SUPPORTED_GRAPHINDEX_EXTS'`). The constant
is now present verbatim in `helpers.py`.

### `core/agents/factory.py` (1404 L) → `core/agents/factory/`

Mixin pattern; 15 bare `AgentFactory.` staticmethod references across mixin
bodies require `_bind_runtime()` in every mixin module.

| Module | Contents |
|--------|----------|
| `shared.py` | `logger`, `DEFAULT_AGENT_GUARDRAILS`, `REASONING_FRAMEWORK` |
| `validation.py` | `_AgentValidationMixin` — `_validate_agent_config` |
| `prompting.py` | `_AgentPromptingMixin` — prompt construction, skill injection, context augmentation |
| `llm.py` | `_AgentLLMMixin` — `_create_llm(_with_fallbacks)`, middleware/hook setup, subagent task tool, callbacks |
| `assembly.py` | `_AgentAssemblyMixin` — `create_agent`, `create_rlm_agent` |
| `__init__.py` | `class AgentFactory(...)` + `create_agent_from_template` + `services.agent_utils` re-exports (`SUPPORTED_MODELS` etc.) |

Verified: all 15 moved nodes AST-identical; `import main` boots; `_bind_runtime`
patches all 4 mixin modules; 37 factory-related tests collect cleanly.

## Verification methodology

For every split, before committing:

1. **AST parity** — byte-for-byte diff of each method body, class docstring,
   decorators, and module-level symbols against `git show HEAD:<file>`.
2. **Import-order smoke tests** — parent-first and each sub-module-first imports
   succeed (guards against the `include_router` route-loss bug).
3. **Late-binding check** — `base.ToolFactory is ToolFactory` resolves.
4. **Runtime smoke** — `import main` + targeted pytest on affected modules.

## Test cleanup (commit `0ff16d1`)

`2c2bb5e` (2026-06-29) deliberately removed legacy graphindex code from
`api/knowledge/rag.py` but left tests referencing it, which broke pytest
collection. Fixed:

- `tests/integration/test_agent_factory_refactor.py` — repaired 3 missing `#`
  comment markers (SyntaxError); guarded the token-tracking import with
  `pytest.importorskip` (production guards it with try/except).
- `scripts/test_groq.py` — lazy `groq` import; missing package no longer breaks
  collection.
- Deleted stale tests for removed functions: `test_pageindex_full_content_loader.py`,
  `test_graphindex_pdf_chat_flow.py`, `test_graphindex_search_via_neo4j.py`,
  `test_neo4j_autosync.py`. The modern `Neo4jDocumentIndex` API keeps its own
  coverage (`test_neo4j_document_index.py`, `test_neo4j_document_enrichment.py`).

## Current test suite

As of the docs-truth pass: `15 failed, 196 passed, 3 skipped, 10 errors` (224 tests
collected, 6.8s). Two migration-test bugs were fixed in the pass (async
`TEST_DATABASE_URL` forwarded to the sync alembic subprocess; `import alembic.env`
can never resolve — the local `backend/alembic/` dir is not a package), so the
non-destructive migration tests now pass. Remaining failures are pre-existing and
fall into four buckets:

- **Destructive migration-cycle tests** (`test_migrations.py`:
  `test_migration_upgrade_head` / `_downgrade_one` / `_idempotency` /
  `_full_cycle`) — the `001_initial_schema` chain is **not replayable on an empty
  database** (documented in `docs/system-architecture.md` §4a: the project uses
  `create_all` + `alembic stamp head`, never replay). These tests downgrade/upgrade
  the shared `langconfig_test` DB and are inherently incompatible with that model.
- **Stale tests for removed Phase 5/6 API** (`test_db_backed_model_runtime.py`,
  `test_models_db_refactor.py`) — reference `routes.encryption_service`,
  `api.system.settings.get_available_models`, and `SUPPORTED_MODELS`/model IDs that
  no longer exist after the DB-driven model + `.env`-key migrations (README Phase
  5/6). Per this file's earlier stale-test policy (commit `0ff16d1`), they should be
  deleted or rewritten against the current API.
- **SQLite-vs-JSONB fixture mismatch** (`test_critical_safety.py`, 10 errors) — the
  `db_engine` fixture uses `sqlite:///:memory:` but the ORM models use Postgres
  `JSONB`, which SQLite cannot render. The fixture needs a Postgres test DB or a
  JSONB type variant.
- **One integration assertion drift** (`test_agent_factory_refactor.py`:
  `test_interrupt_configuration_custom_nodes`) — expects an `agent` node name that
  the current langchain `create_agent` graph no longer exposes.

None of these touch the refactored modules.

## Optional next steps

- Split remaining large modules (largest remaining single files).
- Fix the pre-existing environmental test failures (start PostgreSQL, configure
  pytest-asyncio, prune stale mongodb tests).
- Fix the flagged `upload_document` `NameError` (`industry`/`player` etc.
  referenced before assignment in the bulk-upload loop).
