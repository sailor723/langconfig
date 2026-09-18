# LangConfig DeepAgents — Definition, Configuration & Runtime Build

**Scope.** This document is a precise map of how DeepAgents are *defined* (Pydantic schema +
SQLAlchemy persistence), *configured* (CRUD API, prompt assembly, export), and *built at
runtime* (the `DeepAgentFactory.create_deep_agent` pipeline), plus how chat sessions
instantiate and cache them. It is a research report only — no files were modified.

**Stack versions observed:** `deepagents==0.7.1` (vendored at
`backend/.venv/lib/python3.13/site-packages/deepagents/`), LangChain v1.x / LangGraph,
FastAPI backend at `backend/`. All line numbers refer to the current tree at commit time of
writing. Files cited with `file:line` shorthand:

- `models/deep_agent.py` → `backend/models/deep_agent.py`
- `models/enums.py` → `backend/models/enums.py`
- `api/deep_agents.py` → `backend/api/agents/deep_agents.py`
- `factory/assembly.py` → `backend/services/deepagent_factory/assembly.py`
- `factory/support.py` → `backend/services/deepagent_factory/support.py`
- `factory/preflight.py` → `backend/services/deepagent_factory/preflight.py`
- `factory/shared.py` → `backend/services/deepagent_factory/shared.py`
- `middleware/deep.py` → `backend/core/middleware/deep.py`
- `tools/defaults.py` → `backend/core/tools/defaults.py`
- `chat/messages.py` → `backend/api/chat/messages.py`
- `chat/session.py` → `backend/api/chat/session.py`
- `chat/schemas.py` → `backend/api/chat/schemas.py`
- `chat/shared.py` → `backend/api/chat/shared.py`
- `chat_session_manager.py` → `backend/services/chat_session_manager.py`

---

## 0. One-paragraph mental model

A DeepAgent is a LangGraph agent built by the `deepagents` SDK (0.7.1) and wrapped in
LangConfig infrastructure. The authoritative configuration lives in one PostgreSQL row
(`deep_agent_templates`) whose `config` JSON column is validated by the Pydantic
`DeepAgentConfig` model (`models/deep_agent.py:188-300`); three sibling JSON columns hold
middleware / subagents / backend / guardrails sub-configs (mirroring the nested Pydantic
models). At chat time, the backend hydrates a `DeepAgentConfig` from that JSON, resolves a
`BaseChatModel` from the model string, loads native/CLI/custom tools, prepares
subagents, wires middleware instances (Memory / Filesystem / Summarization), stages the
skill catalog for progressive disclosure, selects a storage backend, and calls the SDK's
`create_deep_agent(...)` (`factory/assembly.py:184-726`). The compiled graph is cached per
chat session (keyed by session_id + agent id + agent `updated_at` epoch) so follow-up turns
skip the RAG/context work (`chat/messages.py:780-790, 869-914`). Interruptions
(Human-in-the-Loop) surface as SSE `interrupt` events and are resumed with
`Command(resume={"decisions": [...]})` (`chat/session.py:384-478`).

---

## A. The DeepAgentConfig schema — every field

`DeepAgentConfig` (`models/deep_agent.py:188-300`) is the master Pydantic model. It nests
four sub-models: `SubAgentConfig` (29-110), `MiddlewareConfig` (113-117),
`BackendConfig` (120-141), `GuardrailsConfig` (144-185). Helper factories
`create_default_middleware_config` (489-510), `create_default_backend_config` (513-523),
`create_default_guardrails_config` (526-537) produce the defaults used by the quick-create /
Agent-Creator endpoints and by templates.

### A.0 Enums (`models/enums.py`)

| Enum | Values | Notes |
|---|---|---|
| `SubAgentType` (16-19) | `dictionary`, `compiled` | `str, Enum` so JSON serializes cleanly |
| `MiddlewareType` (22-29) | `todo_list`, `filesystem`, `subagent`, `hitl`, `summarization`, `tool_retry` | `hitl`/`summarization`/`tool_retry` are declared but **not** handled by `DeepAgentsMiddlewareFactory` (see E) |
| `BackendType` (32-38) | `state`, `store`, `filesystem`, `vectordb`, `composite` | |
| `ReasoningEffort` (41-49) | `none`, `low`, `medium`, `high` | Gemini-only knob (maps to thinking_level / thinking_budget); default `low` "Balanced cost/quality" |

### A.1 `SubAgentConfig` (`models/deep_agent.py:29-110`)

| Field | Type / Default | Purpose |
|---|---|---|
| `name` | `str` (required) | Unique subagent identifier |
| `description` | `str = ""` | What the subagent does (drives `task` tool descriptions) |
| `type` | `SubAgentType = DICTIONARY` | `dictionary` = simple dict-based subagent; `compiled` = workflow-based `CompiledSubAgent`. `field_validator('type', mode='before')` (41-72) coerces None/'' → DICTIONARY (legacy rows load) but rejects unknown strings with `ValueError` |
| `template_id` | `Optional[str] = None` | Base template from `AgentTemplateRegistry` (dictionary subagents) |
| `model` | `Optional[str] = None` | Model override; inherits parent if unset |
| `system_prompt` | `Optional[str] = None` | Subagent-specific system prompt |
| `tools` | `List[str] = []` | Tool names for this subagent (overrides parent tools). **Empty ⇒ tools key omitted at build so the subagent inherits the parent's toolset** (see B.6) |
| `middleware` | `List[str] = []` | Middleware names to enable for the subagent (`todo_list` / `filesystem`) |
| `interrupt_on` | `Dict[str, Any] = {}` | HITL config (overrides parent default) |
| `skills` | `List[str] = []` | Skill source paths (does **not** inherit from parent) |
| `response_format` | `Optional[Dict[str, Any]] = None` | Structured output schema for the subagent |
| `workflow_id` | `Optional[int] = None` | ID of workflow to compile as a `CompiledSubAgent` |
| `workflow_config` | `Optional[Dict[str, Any]] = None` | Override config for the workflow (input mapping, etc.) |

`model_validator(mode='after')` `validate_subagent_consistency` (91-110): `compiled`
requires `workflow_id`; `dictionary` must **not** have `workflow_id`.

### A.2 `MiddlewareConfig` (`models/deep_agent.py:113-117`)

| Field | Type / Default | Purpose |
|---|---|---|
| `type` | `MiddlewareType` (required) | Which middleware |
| `enabled` | `bool = True` | Active flag |
| `config` | `Dict[str, Any] = {}` | Middleware-specific settings (e.g. `{"auto_track": True}`) |

### A.3 `BackendConfig` (`models/deep_agent.py:120-141`)

| Field | Type / Default | Purpose |
|---|---|---|
| `type` | `BackendType = STATE` | `state`, `store`, `filesystem`, `vectordb`, `composite` |
| `config` | `Dict[str, Any] = {}` | Backend-specific settings |
| `mappings` | `Optional[Dict[str, Dict[str, Any]]] = None` | Path mappings for composite backends, e.g. `{"/memory/": {"type": "vectordb", "config": {}}}` |

`model_validator` (132-141): `COMPOSITE` requires non-empty `mappings`.
**Important:** this whole sub-model is *stored* (as the `backend_config` column) but is
**not consulted at build time** — the factory picks the backend from skills/sandbox/storage
mode instead (see B.12 and E.8).

### A.4 `GuardrailsConfig` (`models/deep_agent.py:144-185`)

| Field | Type / Default | Purpose |
|---|---|---|
| `interrupts` | `Dict[str, Any] = {}` | Tool-specific interrupt config: `True` or an `InterruptOnConfig`-style dict per tool name; key `"tools"` is a wildcard resolved at build time |
| `token_limits` | `Dict[str, int] = {"max_total_tokens": 100000, "eviction_threshold": 80000, "summarization_threshold": 60000}` | Token management thresholds |
| `enable_auto_eviction` | `bool = True` | Auto-evict large tool results to filesystem |
| `enable_summarization` | `bool = True` | Auto-summarize conversation history |
| `long_term_memory` | `bool = False` | Workflow-scoped long-term memory via LangGraph Store |

`model_validator` (171-185) enforces `summarization_threshold < eviction_threshold <
max_total_tokens`. **Not all of this is enforceable at runtime** — the SDK 0.7.x has no
`guardrails=` parameter; only `interrupts` is translated into `interrupt_on=`
(factory/assembly.py:597-699), and `long_term_memory` has no consumer (E.7).

### A.5 `DeepAgentConfig` master fields (`models/deep_agent.py:188-300`)

**Model config**

| Field | Type / Default | Purpose |
|---|---|---|
| `model` | `Optional[str] = None` | Model string; falls back to `settings.default_model` from DB (`core.settings.resolve_value(db, "models")`, api/deep_agents.py:310-316) |
| `temperature` | `float = 0.7` (`ge=0.0, le=2.0`) | Generation temperature |
| `max_tokens` | `Optional[int] = None` | Max output tokens; factory substitutes `4096` when None (factory/assembly.py:553-555) |
| `reasoning_effort` | `Optional[ReasoningEffort] = LOW` | Gemini reasoning effort (none/low/medium/high) — **no runtime consumer** (E.3) |
| `modalities` | `Optional[List[str]] = None` | Multimodal modalities e.g. `["image", "text"]` — **no runtime consumer** (E.3) |

**Prompt**

| Field | Type / Default | Purpose |
|---|---|---|
| `system_prompt` | `str` (required) | The agent's authored system prompt (the `USER` slot in prompt assembly) |

**Tools**

| Field | Type / Default | Purpose |
|---|---|---|
| `tools` | `List[str] = []` | Generic tool names — stored but **not loaded** by the deep path (only native/cli/custom are; see E.12) |
| `native_tools` | `List[str] = []` | Native Python tool categories. **Empty ⇒ the 35-tool `DEFAULT_NATIVE_TOOLS` universal base is materialized into the DB config at create/update** (api/deep_agents.py:330-332, 531-533; tools/defaults.py:37-84) |
| `cli_tools` | `List[str] = []` | CLI tool categories (loaded via `ToolLoader.load_cli`) |
| `custom_tools` | `List[str] = []` | User-created custom tool IDs (loaded via `ToolLoader.load_custom`) |

**DeepAgents-specific**

| Field | Type / Default | Purpose |
|---|---|---|
| `use_deepagents` | `bool = True` | Framework toggle; `False` routes chat through the regular `AgentFactory.create_agent` instead (chat/messages.py:393-405, 882-895). Missing key defaults to True for legacy rows (`_ensure_deep_agent_config`, api/deep_agents.py:174-194) |
| `use_phase9_graphindex` | `bool = False` | Docstring says: when True, chat streams through `phase9.graphindex_chat_agent` (5-tool + progressive-disclosure agent) instead of a generic agent — **flag is currently orphaned** (no backend/frontend consumer; E.2) |
| `enable_compiled_subagents` | `bool = True` | Enable `CompiledSubAgent` (workflow-based subagents); False silently skips compiled entries (factory/support.py:160-165) |
| `use_local_sandbox` | `bool = False` | If True, builds a `LocalShellBackend` rooted at the task/agent workspace → agent gains the `execute` shell tool (timeout=120, max_output_bytes=100000, inherit_env=True). Warning: runs on the host, no isolation (factory/assembly.py:451-486) |
| `middleware` | `List[MiddlewareConfig] = []` | Middleware configurations |
| `subagents` | `List[SubAgentConfig] = []` | Subagent configurations |
| `backend` | `BackendConfig = BackendConfig()` | Storage backend config (stored, not used at build; E.8) |
| `guardrails` | `GuardrailsConfig = GuardrailsConfig()` | Safety + context management |

**Skills**

| Field | Type / Default | Purpose |
|---|---|---|
| `skills` | `List[str] = []` | Skill IDs loaded from the PostgreSQL `skills` table; synced to the sandbox filesystem at agent creation and fed to progressive disclosure. Note: since the catalog refactor this **pins** extra/custom skills rather than limiting discovery — every agent sees the full builtin+personal catalog via `SkillsMiddleware` (factory/assembly.py:46-179, 488-506) |
| `skill_router_model` | `Optional[str] = None` | Optional separate model that classifies which skill matches the user's request first; only the matched skill is passed to the main agent. **`_run_skill_router` is implemented (preflight.py:51-125) but never invoked** (E.4) |
| `disable_memory_middleware` | `bool = False` | If True, skip loading the project's `AGENTS.md` into the system prompt via `deepagents.MemoryMiddleware`. Default False = MemoryMiddleware ON |

**Normal-agent HITL (only used when `use_deepagents=False`)**

| Field | Type / Default | Purpose |
|---|---|---|
| `interrupt_before` | `Optional[List[str]] = None` | HITL: pause before nodes (`["tools"]` / `["agent"]`) |
| `interrupt_after` | `Optional[List[str]] = None` | HITL: pause after nodes |

**Export flags**

| Field | Type / Default | Purpose |
|---|---|---|
| `export_format` | `str = "standalone"` | `standalone` or `langconfig` |
| `include_chat_ui` | `bool = True` | Include chat interface in standalone export |
| `include_docker` | `bool = False` | Include Docker support in export |

**Notable:** `custom_prompt` / `custom_suffix` (prompt-assembly fields used by the
`PATCH /prompt` endpoint and the preview route) are **not declared** on `DeepAgentConfig`.
They are stored in the raw `config` dict but dropped by Pydantic's default `extra='ignore'`
when a `DeepAgentConfig` is constructed — the factory's `getattr(config, 'custom_prompt',
None)` therefore always reads `None` (E.5).

### A.6 `DeepAgentTemplate` — SQLAlchemy persistence (`models/deep_agent.py:307-377`)

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(200) NN idx | |
| `description` | Text | |
| `category` | String(50) NN idx | |
| `base_template_id` | String(100) idx | If the agent extends a built-in template |
| `workspace_path` | String(500) | User-defined workspace; chat uploads/generated files live here instead of `outputs/agents/agent_{id}/` |
| `agent_docs` | JSON | User-authored instruction docs `{"AGENTS.md": "...", "CLAUDE.md": "..."}` — PostgreSQL is source of truth, materialized into the workspace at chat build time |
| `config` | JSON NN | The `DeepAgentConfig` dict |
| `middleware_config` | JSON NN default list | Middleware dicts |
| `subagents_config` | JSON NN default list | Subagent dicts |
| `backend_config` | JSON NN default dict | |
| `guardrails_config` | JSON NN default dict | |
| `export_settings` | JSON | |
| `usage_count` / `last_used_at` | Int / DateTime | Usage tracking |
| `version` | String(20) default "1.0.0" | |
| `is_public` / `is_community` | Bool default True/False | |
| `created_at` / `updated_at` | DateTime tz | |
| `lock_version` | (via `OptimisticLockMixin`, core/versioning.py:66+) | Optimistic locking; auto-increments on update; `PUT` checks it and returns 409 on conflict (api/deep_agents.py:495-504) |
| `chat_sessions` | relationship | cascade delete-orphan |

### A.7 `ChatSession` / `SessionDocument` ORM (`models/deep_agent.py:380-482`)

`ChatSession` (380-434): `id`, `agent_id` FK→deep_agent_templates, `project_id` FK→projects
(nullable — **scopes the agent workspace per (vault, agent)**), unique `session_id` (uuid),
`user_id`, `messages` JSON, `metrics` JSON, `tool_calls` JSON, `subagent_spawns` JSON,
`context_operations` JSON, `total_cost_usd` Float, `rag_context_tokens` Int, `is_active`
Bool, `checkpoint_id`, timestamps, `ended_at`, `documents` relationship.

`SessionDocument` (437-482): links uploaded files to a session — `session_id` FK,
`file_path`, `filename`, `original_filename`, `file_size`, `mime_type`,
`document_type` (DocumentType enum), `indexing_status` (IndexingStatus enum, default
NOT_INDEXED), `indexed_at`, `indexed_chunks_count`.

### A.8 Default factories

- `create_default_middleware_config()` (489-510): TODO_LIST `{auto_track: True}`,
  FILESYSTEM `{auto_eviction: True, eviction_threshold_bytes: 1000000}`, SUBAGENT
  `{max_depth: 3, max_concurrent: 5}`.
- `create_default_backend_config()` (513-523): `BackendType.COMPOSITE` with mappings
  `/memory/ → vectordb`, `/filesystem/ → filesystem`, `/state/ → state`.
- `create_default_guardrails_config()` (526-537): interrupts `{}`, token_limits
  100000/80000/60000, auto-eviction + summarization on.

---

## B. How a DeepAgent is BUILT at runtime

### B.0 Class layout

`DeepAgentFactory` (`factory/__init__.py:19-23`) is an empty class composed of three mixins:
`_DeepAgentPreflightMixin` (validation + skill router), `_DeepAgentAssemblyMixin`
(the main `create_deep_agent`), `_DeepAgentSupportMixin` (tool loading, subagent prep,
workflow compilation, callbacks, fallback). Each mixin module ends with `_bind_runtime()`
that late-binds the concrete class into module globals to avoid circular imports
(`factory/__init__.py:30-35`, `factory/assembly.py:729-739`, etc.). Shared logger:
`services.deepagent_factory` (factory/shared.py:18).

### B.1 Entry point

```python
async def create_deep_agent(config, project_id, task_id, context, mcp_manager=None,
    vector_store=None, workflow_id=None, custom_output_path=None,
    workspace_root=None, user_message=None, agent_id=None)
    -> Tuple[CompiledStateGraph, List[BaseTool], List[Any]]   # (agent, tools, callbacks)
```
(`factory/assembly.py:184-196`). Returns a compiled LangGraph graph plus the tool list
(used for logging + interrupt resolution) and callbacks (Langfuse).

### B.2 Step 1 — SDK import + preflight

- `from deepagents import create_deep_agent` — if the SDK is missing, silently degrade to
  `_fallback_to_regular_agent` (factory/assembly.py:219-224, factory/support.py:346-382),
  which converts the config into a plain `AgentFactory.create_agent` call (memory/RAG off).
- `_validate_deep_agent_config` (factory/preflight.py:23-49) only warns: model required,
  system_prompt required, temperature in [0, 2]. Cross-field rules live in Pydantic
  validators.
- `_setup_callbacks` (factory/support.py:328-343): adds a Langfuse `CallbackHandler` tagged
  `project_{project_id}`, `task_{task_id}`, `deepagent` when the package is installed.

### B.3 Step 2 — base tools

`_load_base_tools` (factory/support.py:28-55) builds a `workspace_context`
(`{project_id, task_id, workflow_id, custom_output_path, workspace_root}` — only when a
root/override is present) and calls the shared `load_agent_tools`
(`services/agent_utils.py:564-641`):

1. `resolve_native_tools(native_tool_names, enable_default_tools=True)` — configured list
   wins; empty → `DEFAULT_NATIVE_TOOLS` (35 tools); `enable_default_tools=False` is
   **hardcoded True** on this path (agent_utils.py:595; see E.1).
2. Memory tools (`memory_store`, `memory_recall`, `enable_memory` —
   `SIMPLE_MEMORY_TOOL_NAMES`, agent_utils.py:549) are split out and routed to the
   PostgreSQL-backed `SimpleMemory` system (`get_or_create_memory`, agent_utils.py:625-639).
3. Remaining native tools via `ToolLoader.load_native`, CLI tools via
   `ToolLoader.load_cli`, custom tools via `ToolLoader.load_custom`.

`DEFAULT_NATIVE_TOOLS` (`tools/defaults.py:37-84`) — the universal base: reasoning
(`think_tool`, `reasoning_chain`), planning (`write_todos`, `read_todos`), memory
(`memory_store`, `memory_recall`), web (`web_search`, `web_fetch`), filesystem
(`ls`, `read_file`, `read_image`, `write_file`, `edit_file`, `glob`, `grep`,
`delete_file`, `rename_file`, `move_file`, `mkdir`), shell (`bash`), on-demand skill
(`skill`), deliverables (`save_document`), read-only PG introspection
(`pg_list_tables`, `pg_describe_table`, `pg_query`, `pg_list_agents`, `pg_get_agent`,
`pg_list_projects`), analysis (`sqlite_execute`, `sqlite_load_csv`, `python_execute`,
`save_analysis_result`), and the RAG trio (`graphindex_search`, `graphindex_load`,
`doc_index_list`). Excluded by design: `pg_execute` (writes), `browser`, neo4j ops,
meta tools, `tavily_search`, `gen_pptx`, user custom tools (defaults.py:21-24).

### B.4 Step 3 — middleware tools

`DeepAgentsMiddlewareFactory.create_all_tools` (middleware/deep.py:496-551) iterates
`config.middleware` dicts and calls `create_middleware` (452-493):

- `TODO_LIST` → `TodoListMiddleware` (35-181): sync `create_tools()` emits
  `write_todos` / `update_todo_status` / `get_todos` StructuredTools backed by an
  in-memory list; `get_state`/`set_state` for checkpointing.
- `FILESYSTEM` → `FilesystemMiddleware` (188-299): loads `FILESYSTEM_TOOLS`
  (`["ls","read_file","write_file","edit_file","glob","grep"]`,
  `tools/native_tools.py:435`) via `ToolLoader.load_native` and adds a
  `get_evicted_result` tool; `maybe_evict_result` implements the 1 MB auto-eviction
  threshold but is **not wired into any tool-result path** (E.6).
- `SUBAGENT` is **skipped** (526-528) — the SDK auto-creates `SubAgentMiddleware` with the
  `task` tool when `subagents=` is passed.
- `HITL` / `SUMMARIZATION` / `TOOL_RETRY` hit the `ValueError` branch (492-493) and are
  caught + logged as errors, contributing no tools.

Result: `all_tools = base_tools + middleware_tools` (factory/assembly.py:259-260).

### B.5 Step 4 — subagent prep

`_prepare_subagents` (factory/support.py:57-211), called with
`enable_compiled=getattr(config, 'enable_compiled_subagents', True)`:

- **DICTIONARY** (106-156): builds a dict `{name, description, system_prompt}`; `tools` key
  is added **only if** `sub_config.tools` is non-empty (empty ⇒ inherit the parent's
  toolset; explicitly documented, 110-112, 128-130); native tools loaded via
  `ToolLoader.load_native`; optional `model`, `interrupt_on`, `middleware` (resolved via
  `_resolve_subagent_middleware`, 213-250 — `todo_list` may be unavailable in SDK ≥0.7 and
  is skipped with a log; `filesystem` becomes `FilesystemMiddleware(backend=
  FilesystemBackend())`), `skills`, `response_format`.
- **COMPILED** (158-205): gated on `enable_compiled`; requires `workflow_id`; circular
  dependency detection via a `visited_workflows` set both at the subagent level and inside
  workflow node configs (`_load_and_compile_workflow`, 252-325); loads the
  `WorkflowProfile`, builds the graph via `SimpleWorkflowExecutor()._build_graph_from_workflow`,
  compiles **without** a checkpointer ("subagents use parent's checkpoint"), and wraps it in
  `CompiledSubAgent(name, description, runnable=compiled_graph)`.

### B.6 Step 5 — middleware instances (the real stack)

Built in `factory/assembly.py:275-400`. Note the SDK's own middleware is injected **inside**
`create_deep_agent`; these are extra instances placed in the stack:

1. **MemoryMiddleware** (287-329) — default ON unless `disable_memory_middleware`. If the
   agent's own workspace has an `AGENTS.md` (materialized from `agent_docs` by the chat
   path), it is used with a `FilesystemBackend(root_dir=workspace)`; otherwise
   `ensure_agents_md_exists(project_id)` creates/loads `projects/{id}/AGENTS.md` and the
   backend is scoped to `projects/{id}`. `add_cache_control=True` (Anthropic prompt
   caching). Wrapped in `InstrumentedFilesystemMiddleware`? No — MemoryMiddleware is wrapped
   generically via `instrument_deepagents_middleware` which only instruments Filesystem and
   SubAgent classes (services/deepagents_instrumentation.py:223-252), so Memory passes
   through unchanged unless name-matched.
2. **FilesystemMiddleware** (331-367) — only if a `MiddlewareType.FILESYSTEM` entry exists
   and is enabled. Backend root = `workspace_root` (used as-is for per-agent chat
   workspaces) or `get_task_workspace_with_override(...)`. Wrapped in
   `InstrumentedFilesystemMiddleware` (which also does path sanitization — blocks patterns
   like `langconfig`, `backend`, `src`, `.git`, `Users` and rewrites to `outputs/<name>`,
   deepagents_instrumentation.py:74-97).
3. **SummarizationMiddleware** (369-394) — only if `guardrails.enable_summarization`.
   `SummarizationMiddleware(model=config.model, backend=StateBackend(), trigger=("tokens",
   summarization_threshold or 60000), keep=("messages", 20))`. `("tokens", ...)` matches
   langchain ≥1.3.14's renamed context-size kind.
4. **SubAgentMiddleware** — NOT instantiated here; the SDK adds it (with the `task` tool)
   when `subagents=` is passed (396-400).

### B.7 Step 6 — checkpointer

`get_checkpointer()` (`core/workflows/checkpointing/manager.py:265+`) returns a global
`PostgresSaver` (or None). Passed as `checkpointer=` so chat conversations persist per
`thread_id` (factory/assembly.py:403-409).

### B.8 Step 7 — system prompt assembly (LangConfig side)

`prompt_parts = [config.system_prompt]` + `getattr(config, 'custom_prompt', None)` +
`getattr(config, 'custom_suffix', None)` joined with `"\n\n"`
(factory/assembly.py:421-428). **As noted, `custom_prompt`/`custom_suffix` are not
declared on `DeepAgentConfig` and are dropped by Pydantic, so in practice this produces just
`system_prompt`** (E.5). Then, if the tool set intersects
`{"web_search", "tavily_search", "web_fetch", "ddg_search"}`, a "Web research efficiency"
block is appended (batch searches, ≤8 search calls, don't re-search, move on after
rate-limits) (433-446). The SDK later applies harness-profile BASE/SUFFIX slots around this
(see D).

### B.9 Step 8 — local sandbox

If `use_local_sandbox` (factory/assembly.py:451-486): pick `sandbox_path` (workspace_root →
`outputs/default/` when no workflow → task workspace), then
`LocalShellBackend(root_dir=..., timeout=120, max_output_bytes=100000, inherit_env=True)`.
This gives the agent the `execute` tool.

### B.10 Step 9 — skills staging (progressive disclosure)

`_stage_skill_catalog` (factory/assembly.py:46-179) returns
`(skills_staging_root, skills_sources, db_skills_backend)`:

- **db storage mode** (`settings.storage_mode == "db"`): persists the **entire** `skills`
  table to storage under canonical keys (`skill_storage_key`, `skill_row_to_markdown`),
  sources = `["/skills/{source_type}"]` for each distinct normalized type, backend =
  `DbBackend()`.
- **local mode**: stage `DEFAULT_BUILTIN_SKILLS_ROOT` (env `BUILTIN_SKILLS_ROOT`, default
  `backend/skills/builtin`) into `<root>/skills/builtin` and `PERSONAL_SKILLS_ROOT` (env
  `PERSONAL_SKILLS_ROOT`, default `backend/skills/personal`) into `<root>/skills` (personal
  wins name collisions); sources = `["skills/builtin", "skills"]`. `config.skills` entries
  living outside the global roots are copied additionally (pins). Staging root = sandbox
  path, workspace_root, or the task workspace.

The `SkillsMiddleware` (injected by the SDK when `skills=` is passed) preloads the metadata
catalog (name + description + path) into the system prompt; the agent reads each `SKILL.md`
body on demand via `read_file`. Since this refactor, `config.skills` **pins** extras rather
than limiting discovery (assembly.py:488-506).

### B.11 Step 10 — filesystem dedup

When a disk backend is present (`has_disk_backend` = sandbox or staged skills or
DbBackend), the SDK always injects its own FilesystemMiddleware, so LangConfig drops its
own instrumented copy (via `_is_filesystem_middleware`, 27-43) and removes native fs tools
`{ls, read_file, write_file, edit_file, glob, grep}` from `all_tools` to avoid duplicate
tool names in the model schema (factory/assembly.py:517-545). Without a disk backend the
SDK's fs tools are in-memory no-ops, so the native copies stay (disk writes keep working).

### B.12 Step 11 — model + agent kwargs + backend selection

- Model: `await resolve_model(config.model or DEFAULT_MODEL, config.temperature,
  config.max_tokens or 4096, {"streaming": True})` (`services/agent_utils.py:315-454`):
  looks up the provider from the DB `models` table, then dispatches: deepseek →
  `init_chat_model(model_provider="deepseek")`; `local-*`/`ollama-*`/`lmstudio-*`/`vllm-*`/
  `litellm-*` → `LocalModelService` + `build_local_chat_model`; gpt→openai, claude→anthropic,
  gemini→google_genai (with `convert_system_message_to_human=True`), agnes/minimax/kimi/
  qwen/glm → OpenAI-compatible with provider base URLs; unknown → OpenAI-compatible default.
  API keys come from the DB (`get_api_key_from_db`), not env.
- `agent_kwargs = {model, tools, system_prompt, middleware, subagents, checkpointer}`
  (factory/assembly.py:556-563).
- **Backend selection** (565-595), which **replaces** the stored `BackendConfig`:
  - db-visible skills + sandbox → `CompositeBackend(default=local_sandbox_backend,
    routes={"/skills/": DbBackend(storage_prefix="skills")})`
  - db-visible skills only → `DbBackend` (+ `skills=skills_sources`)
  - sandbox only → `LocalShellBackend` (gives `execute`)
  - staged skills only → `FilesystemBackend(root_dir=skills_staging_root)` (+
    `skills=skills_sources`)

### B.13 Step 12 — guardrails → interrupts + harness profile

`factory/assembly.py:597-699`:

- `guardrails_config["interrupts"]` → `interrupt_on` dict keyed by **actual tool names**:
  key `"tools"` expands to every loaded tool name (the SDK's
  `HumanInTheLoopMiddleware` checks `interrupt_on[tool_call["name"]]`); `True` (or truthy)
  values become `{"allowed_decisions": ["approve", "edit", "reject", "respond"],
  "description": "Approve tool action?"}`; dict values pass through; falsy → skipped.
- When interrupts exist, a `HarnessProfile` is registered under the resolved model key
  `"{provider}:{identifier}"` (from `deepagents._models.get_model_provider/
  get_model_identifier`) with `excluded_tools=frozenset({"write_todos",
  "update_todo_status", "get_todos", "ls", "glob", "grep", "execute", "task"})`
  (645-677) — so the SDK hides its built-in harness tools that LangConfig replaces.
- `guardrails=` is **never passed** to the SDK (0.7.x signature has no such param — it
  would raise TypeError); the code logs a warning that token_limits/auto_eviction are not
  SDK-enforced and that SummarizationMiddleware handles summarization (679-694).
- `create_deep_agent(**agent_kwargs)` (695).
- **No silent fallback** on build failure: any exception other than the initial ImportError
  is re-raised as `RuntimeError(f"Failed to build DeepAgent: ...")` (713-726) — previously
  it silently degraded to a plain agent.

### B.14 What the SDK does with these kwargs (deepagents 0.7.1)

`deepagents/graph.py:268-288` — `create_deep_agent(model, tools, *, system_prompt,
middleware, subagents, skills, memory, permissions, backend, interrupt_on,
response_format, state_schema, context_schema, checkpointer, store, debug, name, cache)`.
Default toolset: `ls, read_file, write_file, edit_file, glob, grep, execute, task`
(execute only for sandbox backends). The SDK always injects its own FilesystemMiddleware
(scoped to the backend root), SubAgentMiddleware when `subagents=` is set, and the harness
profile prompt assembly (D).

---

## C. How chat sessions work

### C.1 Session lifecycle

- **POST `/api/chat/start`** (`chat/session.py:34-97`), body `StartChatRequest`
  (`chat/schemas.py:19-23`): `{agent_id: int, user_id?: int, project_id?: int}`.
  Verifies the `DeepAgentTemplate` exists, creates a `ChatSession` row with a fresh
  `uuid4()` `session_id`, empty `messages`, initial `metrics={total_tokens: 0,
  tool_calls: 0, subagent_spawns: 0}`, `is_active=True`. `project_id` becomes the vault
  scope for the agent workspace. Returns `ChatSessionResponse` (schemas.py:69-78).
- **POST `/api/chat/message/stream`** (`chat/messages.py:680-1227`), body
  `SendMessageRequest` (`chat/schemas.py:32-57`): `{session_id: str, message: str,
  project_id?: int, scope?: List[str]}`. `scope` (None/`"all"`/`[]` = no filter) is applied
  to the native tools via `set_graphindex_doc_scope(scope, pid)` so
  graphindex_search/list/load filter to selected docs deterministically (messages.py:723-734).
- **POST `/api/chat/message`** — non-streaming twin (messages.py:283-520), same storage
  flow via `agent_instance.ainvoke`.
- **POST `/api/chat/{session_id}/resume`** (session.py:384-478) and alias
  **`/api/chat/{session_id}/approve`** (messages.py:1359-1371): HITL resume using
  `Command(resume={"decisions": [{"type": action} ...]})` on the cached agent, thread_id =
  session_id. Requires the cached agent (400 if absent).
- **POST `/api/chat/{session_id}/end`** (session.py:100-151): marks inactive, removes the
  cached agent, deletes LangGraph checkpoints for the thread.
- Supporting endpoints: `/sessions` list, `/health`, `/{session_id}/recover` (+ `/restore`)
  — restores messages from the `checkpoints` table via pickle decode (session.py:249-375);
  `/{session_id}/history`, `/{session_id}/metrics` (pricing table + `ConversationContextService`
  token calc, messages.py:1239-1351); message banking
  `/{session_id}/messages/{idx}/bank` (+ unbank) (messages.py:1374-1442).

### C.2 Streaming turn — build-or-cache (messages.py:741-914)

Inside the SSE generator (dedicated `AsyncSessionLocal` so blocking DB work stays off the
event loop):

1. Re-query the session; append + commit the user message immediately (765-773).
2. `project_id = agent_project_id or request.project_id` (777); `agent_version =
   str(int(agent.updated_at.timestamp()))` (784-785).
3. `agent_instance = get_cached_agent(session_id, agent_id=agent.id,
   agent_version=agent_version)` (786-790). Cache key is the composite
   `"{session_id}:{agent_id}:{agent_version}"` (`chat/shared.py:22-39`,
   `chat_session_manager.py:73-96`); the version component busts the cache when the agent
   config changes. TTL 3600 s, cleanup every 300 s (chat_session_manager.py:57-68, 150-175).
4. **Only on cache miss and when a project_id exists**: RAG context retrieval —
   `context_retriever.retrieve_context(project_id, task_description=request.message,
   similarity_top_k=3, use_hyde=False)` for project docs, plus `similarity_top_k=2` over the
   session's `SessionDocument`s with `indexing_status == READY` (792-833); companion
   `.skill.md` files for uploaded CSVs are injected into `all_context` (844-867). This
   `all_context` is passed as the `context=` arg to `create_deep_agent` — which **ignores
   it** (E.13).
5. Resolve the per-agent workspace: `get_workspace_manager().resolve_agent_workspace(agent,
   session.project_id, vault_key=..., agent_key=...)` (messages.py:873-880) — priority:
   `agent.workspace_path` (absolute as-is; relative resolves against
   `outputs/projects/{vault_key}/`) → vault-scoped default
   `outputs/projects/{vault_key}/agents/{agent_key}/` → legacy `outputs/agents/agent_{id}/`
   (workspace_manager.py:207-255). Then `_materialize_agent_docs(agent, workspace, db)` —
   writes `agent_docs` (or seeds defaults for agents without authored docs and persists them
   back) so MemoryMiddleware + the Files panel see AGENTS.md/CLAUDE.md (messages.py:59-161).
6. Build: `use_deepagents = agent_config.get("use_deepagents", True)`. Regular path →
   `AgentFactory.create_agent(agent_config, project_id, task_id=0, context=all_context, ...,
   workspace_root, agent_id)` (883-895). Deep path →
   `DeepAgentFactory.create_deep_agent(config=DeepAgentConfig(**agent_config), project_id=
   session.project_id or 0, task_id=0, context=all_context, mcp_manager=None,
   vector_store=None, user_message=request.message, workspace_root=agent_workspace_root,
   agent_id=agent.id)` (896-908). `agent_config` = `agent.config` dict + the separate
   `guardrails_config` column merged in (735-738).
7. `cache_agent(...)` with the same composite key (909-914).
8. Fallback: if still None (no project / build failed), build the phase9 graphindex agent
   (`learning/phase9/graphindex/agent.build_agent(project_id=project_id or 1)`) (916-926).

### C.3 Streaming the run (messages.py:928-1143)

- `ExecutionEventCallbackHandler(project_id, task_id=0, workflow_id=None,
  enable_sanitization=True, save_to_db=False)` (929-935) tracks tool calls / subagent
  activity for SSE.
- File content previously uploaded is re-injected: assistant messages containing
  `Content: "..."` are prepended to the user question (941-949).
- `agent_instance.astream_events({"messages": [HumanMessage(augmented_content)]},
  config={"configurable": {"thread_id": session_id}, "callbacks": [event_handler],
  "recursion_limit": 500}, version="v2")` (958-966). The checkpointer loads prior history
  from the thread.
- SSE event types: `tool_start`/`tool_end` (with skill-name detection from `/skills/`
  paths or the `task` tool's subagent_type arg, 973-1014), `custom_event` (1017-1020),
  `chunk` (token streaming through the `StreamingFilter`/ThinkFilter which strips
  `<think>…</think>` and `<tool_call>…</tool_call>` and separately emits a `thinking` event,
  1023-1059), `interrupt` (from `__interrupt__` events, 1061-1071).
- Post-stream interrupt detection (1073-1117): `agent_instance.aget_state` — deep-agent
  interrupts surface via `state_snapshot.interrupts` (GraphInterrupt /
  HumanInTheLoopMiddleware), regular-agent pauses via `state_snapshot.next` + the last
  AIMessage's `tool_calls`. Interrupt ⇒ no `complete` event.
- `GraphInterrupt` exception path (1131-1142); generic error → `error` event (1144-1146).
- Persistence (1148-1222): assistant message, metrics (`total_tokens`, `rag_context_tokens`,
  `tool_calls`), `tool_calls` list, and a `ConversationArchive` turn record.
- Response: `StreamingResponse(generate_stream(), media_type="text/event-stream")` (1224-1227).

---

## D. Prompt-preview / harness-profile logic

### D.1 Assembly order (SDK semantics)

The SDK's assembly order is **USER → (BASE) → SUFFIX**:

- `USER` = the caller's `system_prompt=` (LangConfig's `system_prompt`).
- `BASE` = `HarnessProfile.base_system_prompt` when set, otherwise the stack's authored
  base (the main agent has none by default) — `harness_profiles.py:544-559, 780-798`
  (`_apply_profile_prompt`: `prompt = profile.base_system_prompt if ... else base_prompt`;
  then `prompt + "\n\n" + profile.system_prompt_suffix` if a suffix exists).
- `SUFFIX` = `HarnessProfile.system_prompt_suffix` (561+).

LangConfig's own factory additionally prepends `custom_prompt` (as a second USER part) and
`custom_suffix` (as a trailing part) to the `system_prompt` **before** the SDK sees it
(factory/assembly.py:421-428) — but as established, those fields are dropped by Pydantic
(E.5), so effectively only the `USER` slot is authored in LangConfig, and the SDK applies
BASE/SUFFIX from the model's registered harness profile.

### D.2 `HarnessProfile` fields (`harness_profiles.py:483-620`, SDK 0.7.1)

`base_system_prompt: str | None`, `system_prompt_suffix: str | None`,
`excluded_tools: frozenset[str]`, `tool_description_overrides: dict[str, str]`,
`excluded_middleware: frozenset[type]`, `extra_middleware: list[AgentMiddleware]`,
`general_purpose_subagent: GeneralPurposeSubagentProfile | None`. Profiles register under a
provider key (`"openai"`) or `provider:model` key (`"openai:gpt-5.4"`). `_merge_profiles`
(1194-1249) layers model-level profiles over provider-level ones (per-key overrides, union
of excluded sets, middleware merged by class). Built-in profiles shipped with the SDK:
`_anthropic_sonnet_4_6.py`, `_anthropic_haiku_4_5.py` (each registers a
`system_prompt_suffix`), `_openai_codex.py`, `_nvidia_nemotron_3_ultra.py`.

### D.3 `_harness_profile_for_model` (`harness_profiles.py:1252-1322`)

`_harness_profile_for_model(model: BaseChatModel, spec: str | None) -> HarnessProfile`:

1. If `spec` (the original model string) is given → `_get_harness_profile(spec)` (falls
   back internally from exact key to provider prefix) or an empty `HarnessProfile()`.
2. Else derive `identifier`/`provider` from the pre-built instance and try
   `provider:identifier`, then identifier-only (only if it contains a `:`), then the bare
   provider key; returns the default (empty) profile on a miss, logging at WARNING when a
   registry exists but nothing matched.

`api/deep_agents.py:814-899` (`POST /api/deepagents/prompt-preview`) calls it as
`_harness_profile_for_model(None, request.model)` (model=None, spec=model string — the
post-0.7 calling convention where a bare string goes in the `spec` slot, 833-835). The
preview returns segments:

- `USER` — the request's `system_prompt` (editable) (840-847).
- `BASE` (source `harness_profile`) or `CUSTOM` (source `custom`) — user `custom_prompt`
  wins over `profile.base_system_prompt`; the old SDK `BASE_AGENT_PROMPT` constant was
  removed in 0.7, so with no profile base the BASE segment is empty (849-868).
- `SUFFIX` — user `custom_suffix` wins over `profile.system_prompt_suffix` (870-884).
- `assembled` = `"\n\n".join(parts)` (886-899).

`PATCH /api/deepagents/{agent_id}/prompt` (`SavePromptRequest`, 906-943) persists
`custom_prompt`/`custom_suffix` into the agent's raw `config` dict (used by the preview and
export; see E.5 for why the factory can't read them).

### D.4 LangConfig's runtime harness-profile registration

In the factory, a harness profile is registered **only when `guardrails.interrupts` is
non-empty** (factory/assembly.py:645-677): `register_harness_profile(
f"{get_model_provider(main_chat_model)}:{get_model_identifier(main_chat_model)}",
HarnessProfile(excluded_tools=frozenset({"write_todos", "update_todo_status",
"get_todos", "ls", "glob", "grep", "execute", "task"})))`. The key is derived from the
resolved `BaseChatModel` instance (a fix for a previous NameError that made this block dead
code, 650-654). Effect: for agents with HITL configured, the SDK's built-in harness tools
that LangConfig replaces (todo tools come from native tools; fs/execute from the disk
backend) are hidden from the model schema.

---

## E. Notable gaps, TODOs, and half-implemented features

1. **`code_mode` is a regular-agent-only feature.** `DeepAgentConfig` has no `code_mode`
   field. The `run_code` single-tool transport lives in `core/tools/code_mode.py` (AST
   validation, generated tool SDK, forbidden imports/attrs) and is only applied by the
   regular-agent factory (`core/agents/factory/assembly.py:339-341`,
   `agent_config.get("code_mode")`). Deep agents cannot enable code mode; a deep-agent
   `code_mode` key in the config dict is silently dropped by Pydantic.

2. **`use_phase9_graphindex` is orphaned.** Declared at `models/deep_agent.py:215-223` with
   a docstring saying the chat stream should route through `phase9.graphindex_chat_agent`,
   but grep shows **no consumer anywhere** in backend or frontend. The phase9 graphindex
   agent is used only as an emergency fallback when DeepAgent/AgentFactory build fails
   (chat/messages.py:916-926).

3. **`reasoning_effort` / `modalities` are dead fields.** Declared on `DeepAgentConfig`
   (194-201) and tested in `backend/tests/test_deep_agent_validation.py:241-336`, but
   nothing in the factory, `resolve_model`, or chat path reads them. `resolve_model`
   (agent_utils.py:315-454) never maps `reasoning_effort` to Gemini `thinking_level` /
   `thinking_budget`. They are consumed only by the workflow→Streamlit codegen
   (`core/codegen/generators/streamlit_configurable.py:48-100`), not by agents.

4. **Skill router is implemented but never invoked.** `skill_router_model` is declared
   (261-267) and `_run_skill_router` is fully implemented (factory/preflight.py:51-125 —
   builds a routing prompt, strips `deepseek:`/`agnes:` prefixes, gets the API key from DB,
   calls the OpenAI-compatible endpoint at temperature 0.1 / max_tokens 20, validates the
   returned skill_id, falls back to "all skills" on any error). However, `create_deep_agent`
   accepts `user_message` (the router input) but never calls the router — `user_message` is
   referenced only in the docstring (factory/assembly.py:194, 213). The `scripts/set_skill_router.py`
   helper writes the flag into configs, so this is a configured-but-inert feature.

5. **`custom_prompt`/`custom_suffix` are dropped at build time.** They are stored in the
   raw `config` dict (`PATCH /prompt`, api/deep_agents.py:906-943), preserved through
   `PUT` (511-540), previewed (`/prompt-preview`), and exported (`build_agent_bundle`),
   but `DeepAgentConfig` does not declare them and has no `model_config extra="allow"`, so
   `DeepAgentConfig(**agent_config)` (chat/messages.py:897) silently discards them and the
   factory's `getattr(config, 'custom_prompt', None)` (factory/assembly.py:424-427) is
   always None. The intended USER→CUSTOM→SUFFIX prompt assembly therefore collapses to
   `system_prompt` (+ web-research hints) at runtime. Either the fields should be declared
   on the model or the assembly should read from the raw dict.

6. **Auto-eviction is half-wired.** `GuardrailsConfig.enable_auto_eviction` defaults True,
   `FilesystemMiddleware.maybe_evict_result` (middleware/deep.py:257-289) implements the
   1 MB threshold + `get_evicted_result` retrieval tool, but nothing calls
   `maybe_evict_result` (no tool-result interceptor), and the SDK 0.7.x has no
   `guardrails=` parameter, so `token_limits`/auto-eviction are **not enforced** — the
   factory logs exactly this warning (factory/assembly.py:679-694). Summarization is the
   only guardrail that actually executes (via SummarizationMiddleware).

7. **`long_term_memory` has no consumer.** Declared (166-169) but never read; the factory
   never passes a LangGraph `store=` to `create_deep_agent` (agent_kwargs has only
   checkpointer). Also note the SDK param is `store`, and LangConfig's default backend
   config maps `/memory/ → vectordb`, but none of that is plumbed.

8. **`BackendConfig` (type/config/mappings) is stored but not used at build time.** The
   factory chooses the backend purely from runtime signals: db-visible skills →
   `DbBackend`/`CompositeBackend`, `use_local_sandbox` → `LocalShellBackend`, staged skills
   → `FilesystemBackend` (factory/assembly.py:565-595). The user-authored
   `backend.type`/`mappings` (including the composite `/memory/`, `/state/` routes) are
   never consulted, so `BackendType.STORE`/`VECTORDB` and the composite mappings are inert
   configuration.

9. **Middleware enum surface exceeds the implementation.** `MiddlewareType.HITL`,
   `SUMMARIZATION`, `TOOL_RETRY` exist in the enum (models/enums.py:22-29) but
   `DeepAgentsMiddlewareFactory.create_middleware` raises `ValueError` for them
   (middleware/deep.py:492-493) — such config entries log errors and yield no tools. HITL
   is instead handled through `guardrails.interrupts → interrupt_on`; summarization is
   driven by `guardrails.enable_summarization`, not by a `MiddlewareConfig` entry.

10. **Legacy `SubAgentMiddleware`/`TodoListMiddleware` in `core/middleware/deep.py` are
    scaffolding.** The `spawn_subagent` tool literally returns
    `"[Subagent execution would happen here]"` (middleware/deep.py:366-389) — real
    subagent spawning is done by the SDK's `SubAgentMiddleware`/`task` tool and
    `_prepare_subagents`. The LangConfig copy of `TodoListMiddleware` duplicates the native
    `write_todos`/`update_todo_status`/`get_todos` tools that already ship in
    `DEFAULT_NATIVE_TOOLS`, so an agent with defaults + default middleware can receive
    duplicate todo tools; the harness profile that hides them is registered only when
    interrupts are configured (E.14).

11. **`enable_default_tools` is not part of `DeepAgentConfig`.** The regular-agent path
    reads it (`core/agents/tool_loader.py:109`, `core/agents/factory/assembly.py:73`), but
    `load_agent_tools` hardcodes `enable_default_tools=True` for the deep path
    (agent_utils.py:595). A deep agent cannot opt out of the 35-tool universal base without
    configuring an explicit non-empty `native_tools` list.

12. **`config.tools` is vestigial.** The plain `tools` list (205-206) is used by the
    quick-create/Agent-Creator endpoints and standalone codegen, but `_load_base_tools`
    only reads `native_tools`, `cli_tools`, `custom_tools` (factory/support.py:47-54). A
    `tools`-only agent would get the default native base instead.

13. **`context` (RAG) and `user_message` args are ignored by the deep path.** The chat
    stream invests in RAG retrieval (`all_context`, chat/messages.py:792-867) and passes it
    as `context=`; the regular-agent factory uses it, but `create_deep_agent` never reads
    `context` (only the fallback path passes it through, factory/assembly.py:223). Same for
    `user_message` (E.4). So for deep agents, project/session document retrieval and skill
    routing are computed but never reach the agent.

14. **Harness-profile exclusion is conditional.** The registered profile that hides
    `write_todos/update_todo_status/get_todos/ls/glob/grep/execute/task` is only registered
    inside the `if interrupt_on:` block (factory/assembly.py:641-677). Agents without HITL
    get no profile registration, so the SDK's built-in todo/fs tools and LangConfig's native
    ones can coexist as duplicates in the model schema.

15. **Chat dual-storage drift risk.** Conversation state lives in two places: the
    PostgreSQL `ChatSession.messages` JSON and the LangGraph checkpointer (thread_id =
    session_id). The stream appends the user message to DB immediately, saves the assistant
    message in `finally` (only when `full_response` is non-empty — interrupted turns leave
    the DB without an assistant message), and archives turns to `ConversationArchive`. The
    `recover` endpoints exist to reconcile the DB from checkpoints, acknowledging the
    split-brain risk (chat/session.py:249-375, "BUG FIX" comments at 196-199).

16. **`context_operations` (evictions/summarizations) is never populated.** The
    `ChatSession.context_operations` column exists (models/deep_agent.py:409) and is
    surfaced in metrics, but nothing writes to it in the chat path — consistent with E.6
    (no actual eviction/summarization bookkeeping on the session).

17. **Fallback ordering quirk.** If the deep/regular build returns None (or the project_id
    is missing), the stream silently substitutes the phase9 graphindex agent
    (chat/messages.py:916-926). Combined with B.14's "no silent fallback inside the
    factory," this means a deep-agent build failure surfaces as an error, but a None result
    (e.g. no project bound) silently swaps in a different agent with the same session
    thread.

18. **`export_format`/`include_chat_ui`/`include_docker`** are declared and stored but the
    actual export endpoint (`GET /api/deepagents/{id}/export`) always emits a v1.1
    `.langconfig.json` bundle via `build_agent_bundle` regardless of these flags
    (api/deep_agents.py:1000-1028; agent_bundle.py:162+ bundles full config + embedded
    custom tools/skills with secrets redacted). `GET /api/deepagents/{id}/code` emits a
    fully standalone Python script (api/deep_agents.py:1031-1494) that inlines LLM config,
    system prompt (+ attached skills), tool source, and the DeepAgentState schema — also
    ignoring those flags.

19. **`use_deepagents=False` legacy normalization in `send_message`.** The non-streaming
    endpoint force-defaults a `guardrails` dict `{"input": [], "output": []}` when the
    stored config lacks it (chat/messages.py:370-371) — a shape that contradicts the
    `GuardrailsConfig` model (`interrupts`/`token_limits`/…), another sign the config dict
    and the Pydantic model have drifted.

---

## Quick reference: where each build ingredient comes from

| Ingredient | Source | Location |
|---|---|---|
| LLM instance | `resolve_model(model, temperature, max_tokens or 4096, {"streaming": True})` | factory/assembly.py:550-555; agent_utils.py:315-454 |
| Base tools | `load_agent_tools(native, cli, custom)`; empty native → `DEFAULT_NATIVE_TOOLS` | factory/support.py:28-55; agent_utils.py:564-641; tools/defaults.py:37-84 |
| Middleware tools | `DeepAgentsMiddlewareFactory.create_all_tools` | factory/assembly.py:251-256; middleware/deep.py:496-551 |
| Subagents | `_prepare_subagents` (dict + CompiledSubAgent) | factory/support.py:57-211 |
| MemoryMiddleware | project/agent `AGENTS.md` via FilesystemBackend | factory/assembly.py:287-329; agents_md_service.py:95-108 |
| FilesystemMiddleware | workspace root via FilesystemBackend | factory/assembly.py:331-367 |
| SummarizationMiddleware | trigger `("tokens", threshold)`, keep 20 msgs | factory/assembly.py:369-394 |
| Checkpointer | `get_checkpointer()` → PostgresSaver | factory/assembly.py:403-409 |
| System prompt | `system_prompt` + (dropped) custom_prompt/suffix + web hints | factory/assembly.py:421-446 |
| Sandbox | `LocalShellBackend` when `use_local_sandbox` | factory/assembly.py:451-486 |
| Skills | `_stage_skill_catalog` (db or local staging) | factory/assembly.py:46-179, 488-506 |
| Backend | DbBackend / CompositeBackend / LocalShellBackend / FilesystemBackend | factory/assembly.py:565-595 |
| HITL | `guardrails.interrupts` → `interrupt_on` + harness profile | factory/assembly.py:597-699 |
| Chat thread | `thread_id = session_id`, checkpointer persistence | chat/messages.py:958-966 |
| Agent cache | `ChatSessionManager` composite key + TTL | chat_session_manager.py:73-148; chat/shared.py:22-57 |

*Report end.*
